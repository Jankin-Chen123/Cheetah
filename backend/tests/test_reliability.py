from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx
import pytest
from conftest import drain, post, published_job
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.core.models import Artifact, Budget, IntakeJob, OutboxEvent, Task, utcnow
from app.core.tasks import claim, enqueue, fence, reserve_model


def test_worker_completion_and_event_are_atomic_and_internal_retry_is_single_step(
    api, runtime, monkeypatch
):
    job_id, _ = published_job(api, runtime)
    received = post(
        api,
        f"/jobs/{job_id}/resume-batches",
        {
            "execution_mode": "mock",
            "items": [{"client_item_id": "one", "name": "虚构.txt", "text": "工作年限：5"}],
        },
        expected=202,
    )
    import app.worker as worker

    original = worker.publish_handoff

    def fail(*args):
        raise RuntimeError("fixture interrupted before commit")

    monkeypatch.setattr(worker, "publish_handoff", fail)
    drain(runtime)
    with Session(runtime[1]) as db:
        assert not list(db.scalars(select(Artifact).where(Artifact.type == "D06")))
        assert not list(db.scalars(select(OutboxEvent)))
        task = db.scalar(select(Task).where(Task.kind == "screening"))
        task_id, revision = task.id, task.revision
        assert task.status == "failed"
    monkeypatch.setattr(worker, "publish_handoff", original)
    post(
        api,
        f"/tasks/{task_id}/retry",
        {"expected_revision": revision, "reason": "恢复内部计算"},
        expected=202,
    )
    drain(runtime)
    with Session(runtime[1]) as db:
        for kind in ("D03", "D04", "D05", "D06"):
            assert len(list(db.scalars(select(Artifact).where(Artifact.type == kind)))) == 1
        assert len(list(db.scalars(select(OutboxEvent)))) == 1
    assert api.get(f"/api/v1/tasks/{received['task_id']}").json()["status"] == "completed"


def test_expired_worker_fenced_and_external_unknown_is_not_requeued(api, runtime):
    job_id, _ = published_job(api, runtime)
    settings, engine = runtime
    with Session(engine) as db, db.begin():
        task = enqueue(
            db,
            organization_id="fixture-org",
            job_id=job_id,
            kind="research",
            dedup_key="fixture-recover",
            payload={},
        )
        task_id = task.id
    with Session(engine) as db, db.begin():
        old = claim(db, settings, {"research"})
    with Session(engine) as db, db.begin():
        db.get(Task, task_id).lease_until = utcnow() - timedelta(seconds=1)
    with Session(engine) as db, db.begin():
        new = claim(db, settings, {"research"})
        assert new[0] == old[0] and new[1] != old[1]
    with Session(engine) as db, db.begin():
        with pytest.raises(DomainError, match="STALE_TASK_LEASE"):
            fence(db, *old)
        task = db.get(Task, task_id)
        task.external_state = "submitted"
        task.lease_until = utcnow() - timedelta(seconds=1)
    with Session(engine) as db, db.begin():
        assert claim(db, settings, {"research"}) is None
        assert db.get(Task, task_id).status == "reconciling"
    response = api.get(f"/api/v1/tasks/{task_id}").json()
    assert not response["retryable"]


def test_budget_reservation_is_atomic(api, runtime):
    job_id, _ = published_job(api, runtime)
    with Session(runtime[1]) as db, db.begin():
        budget = db.get(Budget, job_id)
        budget.call_limit = 1
        ids = [
            enqueue(
                db,
                organization_id="fixture-org",
                job_id=job_id,
                kind="job_analysis",
                dedup_key="fixture-budget-" + str(index),
                payload={},
            ).id
            for index in range(2)
        ]

    def reserve(task_id):
        try:
            with Session(runtime[1]) as db, db.begin():
                reserve_model(db, db.get(Task, task_id), 100)
            return "reserved"
        except DomainError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, ids))
    assert sorted(results) == ["BUDGET_EXCEEDED", "reserved"]
    with Session(runtime[1]) as db:
        budget = db.get(Budget, job_id)
        assert budget.reserved == 1 and budget.tokens_reserved == 100


def test_live_timeout_retains_budget_and_never_automatically_resubmits(api, runtime, monkeypatch):
    settings, engine = runtime
    settings.model_endpoint = "https://model.fixture.invalid/chat"
    settings.model_name = "fixture-model"
    from pydantic import SecretStr

    settings.model_api_key = SecretStr("fixture-not-a-real-key")
    job = post(
        api, "/jobs", {"title": "虚构岗位", "company": "虚构公司", "material_text": "虚构需求"}
    )
    accepted = post(
        api,
        f"/jobs/{job['id']}/analyze",
        {"expected_revision": 1, "execution_mode": "live"},
        expected=202,
    )
    calls = []

    def timeout(*args):
        calls.append(1)
        raise httpx.ReadTimeout("fixture external result unknown")

    monkeypatch.setattr("app.worker.analysis.invoke_model", timeout)
    drain(runtime)
    status = api.get(f"/api/v1/tasks/{accepted['task_id']}").json()
    assert status["status"] == "reconciling" and not status["retryable"]
    assert len(calls) == 1
    assert status["budget"]["model_calls"]["reserved"] == 1
    assert status["usage"]["tokens"] is None
    drain(runtime)
    assert len(calls) == 1


def test_concurrent_idempotency_requests_write_one_job(api, runtime):
    if runtime[1].dialect.name != "postgresql":
        pytest.skip("PostgreSQL advisory locks require the PostgreSQL integration run")
    body = {"title": "虚构岗位", "company": "虚构公司", "material_text": "虚构需求"}

    def create(_):
        return api.post(
            "/api/v1/jobs", json=body, headers={"Idempotency-Key": "fixture-concurrent-once"}
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(create, range(4)))
    assert all(r.status_code == 201 for r in responses)
    assert len({r.json()["id"] for r in responses}) == 1
    with Session(runtime[1]) as db:
        assert len(list(db.scalars(select(IntakeJob)))) == 1


def test_concurrent_publish_consumes_draft_revision_once(api, runtime):
    if runtime[1].dialect.name != "postgresql":
        pytest.skip("PostgreSQL row locks require the PostgreSQL integration run")
    job_id, original = published_job(api, runtime)
    job = api.get(f"/api/v1/jobs/{job_id}").json()
    body = {
        "expected_draft_revision": job["draft_revision"],
        "d01_ref": job["d01_ref"],
        "d02_ref": job["d02_ref"],
        "is_test_rule": True,
        "confirmation_note": "并发发布虚构标准",
    }

    def publish(index):
        return api.post(
            f"/api/v1/jobs/{job_id}/rules/publish",
            json=body,
            headers={"Idempotency-Key": f"fixture-publish-concurrent-{index}"},
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(publish, range(3)))
    assert sorted(response.status_code for response in responses) == [201, 409, 409]
    history = api.get(f"/api/v1/jobs/{job_id}/rules/versions/1").json()
    assert history["content"] == original["content"]
