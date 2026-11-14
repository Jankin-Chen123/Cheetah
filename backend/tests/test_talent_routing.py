"""Routing retains people and creates pending associations, never hiring decisions."""

import json
from uuid import uuid4

import httpx
from conftest import drain, post, published_job
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.models import Application, Artifact, Identity, IntakeJob, OutboxEvent, Talent, Task
from app.modules.intake import analysis


def import_text(api, text, *, key=None, mode="mock"):
    return post(
        api,
        "/talent-imports",
        {
            "execution_mode": mode,
            "items": [{"client_item_id": "one", "name": "虚构简历.txt", "text": text}],
        },
        key=key,
        expected=202,
    )["items"][0]


def routing_job(api, runtime, directions):
    job_id, _ = published_job(api, runtime)
    job = api.get(f"/api/v1/jobs/{job_id}").json()
    response = api.patch(
        f"/api/v1/jobs/{job_id}",
        json={
            "expected_revision": job["revision"],
            "routing_directions": directions,
        },
    )
    assert response.status_code == 200, response.text
    return job_id


def test_talent_intake_without_any_job_retains_unknown_and_classified_people(api, runtime):
    backend = import_text(api, "姓名：虚构乙\n职能：后端开发\n技能：Java、MySQL")
    unknown = import_text(api, "姓名：虚构丙\n期待新的职业机会")
    drain(runtime)
    people = api.get("/api/v1/talents").json()
    assert people["total"] == 2
    for receipt, state in [(backend, "classified"), (unknown, "unclassified")]:
        detail = api.get(f"/api/v1/talents/{receipt['talent_id']}").json()
        assert detail["classification_state"] == state
        assert detail["applications"] == []
        task = api.get(f"/api/v1/tasks/{receipt['task_id']}")
        assert task.status_code == 200
        assert task.json()["resource_type"] == "talent"
        assert task.json()["status"] == "completed"
    with Session(runtime[1]) as db:
        assert db.scalar(select(func.count()).select_from(IntakeJob)) == 0
        assert db.scalar(select(func.count()).select_from(Application)) == 0
        assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 0


def test_backend_routes_only_to_backend_and_fullstack_routes_to_both_without_research(api, runtime):
    front = routing_job(api, runtime, ["frontend"])
    back = routing_job(api, runtime, ["backend"])
    r1 = import_text(api, "姓名：虚构乙\n职能：后端开发\n技能：Java、MySQL")
    r2 = import_text(api, "姓名：虚构丁\n职能：全栈开发\n技能：React、Java")
    drain(runtime)
    one = api.get(f"/api/v1/talents/{r1['talent_id']}").json()
    both = api.get(f"/api/v1/talents/{r2['talent_id']}").json()
    assert {x["job_id"] for x in one["applications"]} == {back}
    assert {x["job_id"] for x in both["applications"]} == {front, back}
    with Session(runtime[1]) as db:
        apps = list(db.scalars(select(Application)))
        assert all(a.stage == "matched" and a.screening_result == "pending" for a in apps)
        assert len({a.candidate_id for a in apps if a.talent_id == r2["talent_id"]}) == 1
        assert not list(db.scalars(select(Task).where(Task.kind.in_(["research", "screening"]))))
        assert not list(db.scalars(select(Artifact).where(Artifact.type.in_(["D04", "D06"]))))
    job_list = api.get(f"/api/v1/jobs/{back}/applications")
    assert job_list.status_code == 200
    assert all(x["stage"] == "matched" for x in job_list.json()["items"])


def test_existing_talent_routes_when_a_new_job_publishes_and_no_duplicate_on_resync(api, runtime):
    receipt = import_text(api, "姓名：虚构乙\n职能：后端开发")
    drain(runtime)
    job_id = routing_job(api, runtime, ["backend"])
    detail = api.get(f"/api/v1/talents/{receipt['talent_id']}").json()
    assert len(detail["applications"]) == 1
    before = detail["applications"][0]["application_id"]
    for _ in range(2):
        detail = post(
            api,
            f"/talents/{detail['id']}/route",
            {"expected_revision": detail["revision"]},
            expected=200,
        )
    assert detail["applications"][0]["application_id"] == before
    assert detail["applications"][0]["job_id"] == job_id
    assert len(detail["applications"]) == 1


def test_import_dedup_and_mixed_file_receipts_do_not_merge_different_people(api, runtime):
    text = "姓名：虚构甲\n职能：前端开发"
    first = import_text(api, text)
    duplicate = import_text(api, text)
    assert duplicate["disposition"] == "duplicate"
    assert first["talent_id"] == duplicate["talent_id"]
    other = import_text(api, "姓名：虚构甲\n职能：后端开发")
    assert other["talent_id"] != first["talent_id"]
    response = api.post(
        "/api/v1/talent-imports",
        headers={"Idempotency-Key": uuid4().hex},
        data={
            "manifest": json.dumps(
                {
                    "execution_mode": "mock",
                    "items": [
                        {"client_item_id": "ok", "filename": "good.txt"},
                        {"client_item_id": "bad", "filename": "bad.exe"},
                    ],
                }
            )
        },
        files=[
            ("files", ("good.txt", text.encode(), "text/plain")),
            ("files", ("bad.exe", b"invalid", "application/octet-stream")),
        ],
    )
    assert response.status_code == 202, response.text
    assert [x["disposition"] for x in response.json()["items"]] == ["duplicate", "invalid"]
    drain(runtime)
    assert api.get("/api/v1/talents").json()["total"] == 2


def test_start_deep_screening_is_explicit_idempotent_and_keeps_mock_source(api, runtime):
    routing_job(api, runtime, ["backend"])
    receipt = import_text(api, "姓名：虚构乙\n职能：后端开发\n工作年限：5")
    drain(runtime)
    detail = api.get(f"/api/v1/talents/{receipt['talent_id']}").json()
    app_id = detail["applications"][0]["application_id"]
    app = api.get(f"/api/v1/applications/{app_id}").json()
    body = {"expected_revision": app["revision"], "reason": "按岗位开始深度初筛"}
    key = uuid4().hex
    first = post(api, f"/applications/{app_id}/start-screening", body, key=key, expected=202)
    replay = post(api, f"/applications/{app_id}/start-screening", body, key=key, expected=202)
    assert first == replay
    response = api.post(
        f"/api/v1/applications/{app_id}/start-screening",
        json=body,
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert response.status_code == 409
    drain(runtime)
    result = api.get(f"/api/v1/applications/{app_id}").json()
    assert result["provenance"]["fixture_only"] is True
    with Session(runtime[1]) as db:
        assert len(list(db.scalars(select(Task).where(Task.kind == "research")))) == 1


def test_manual_classification_versions_and_stale_revisions_do_not_change_started_work(
    api, runtime
):
    routing_job(api, runtime, ["backend"])
    receipt = import_text(api, "姓名：虚构戊\n负责订单系统接口设计。")
    drain(runtime)
    detail = api.get(f"/api/v1/talents/{receipt['talent_id']}").json()
    body = {
        "expected_revision": detail["revision"],
        "directions": [
            {
                "direction_id": "backend",
                "level": "primary",
                "quote": "负责订单系统接口设计。",
                "reason": "职责属于服务端研发",
            }
        ],
        "reason": "补充职能归类",
    }
    response = api.patch(f"/api/v1/talents/{detail['id']}/directions", json=body)
    assert response.status_code == 200, response.text
    new = response.json()
    assert new["profile_version"] == 2 and len(new["applications"]) == 1
    assert new["classification_source"] == "manual"
    assert api.patch(f"/api/v1/talents/{detail['id']}/directions", json=body).status_code == 409
    body["expected_revision"] = new["revision"]
    body["directions"][0]["quote"] = "伪造的原文"
    assert api.patch(f"/api/v1/talents/{detail['id']}/directions", json=body).status_code == 422


def test_permissions_restriction_and_replay_cover_talent_and_downstream_copies(api, runtime):
    routing_job(api, runtime, ["backend"])
    body = {
        "execution_mode": "mock",
        "items": [
            {
                "client_item_id": "one",
                "name": "虚构.txt",
                "text": "职能：后端开发",
            }
        ],
    }
    key = uuid4().hex
    receipt = post(api, "/talent-imports", body, key=key, expected=202)["items"][0]
    drain(runtime)
    detail = api.get(f"/api/v1/talents/{receipt['talent_id']}").json()
    app_id = detail["applications"][0]["application_id"]
    paths = [
        f"/talents/{detail['id']}",
        f"/talents/{detail['id']}/file",
        f"/tasks/{receipt['task_id']}",
        f"/applications/{app_id}",
    ]
    with Session(runtime[1]) as db:
        owner = db.scalar(select(Identity).where(Identity.username == "fixture-owner"))
        owner_org = owner.organization_id
    for name, org in [("fixture-colleague", owner_org), ("fixture-other", "fixture-other-org")]:
        with Session(runtime[1]) as db:
            identity = db.scalar(select(Identity).where(Identity.username == name))
            with TestClient(api.app) as client:
                result = client.post(
                    "/api/v1/auth/login",
                    headers={"Origin": "http://localhost:5173"},
                    json={"username": name, "password": "fixture-password"},
                )
                assert result.status_code == 200
                assert identity.organization_id == org
                assert client.get("/api/v1/talents").json()["total"] == 0
                for path in paths:
                    assert client.get("/api/v1" + path).status_code == 404
    with Session(runtime[1]) as db, db.begin():
        db.get(Talent, detail["id"]).status = "restricted"
    for path in paths:
        assert api.get("/api/v1" + path).status_code == 404
    assert api.get("/api/v1/applications").json()["total"] == 0
    replay = api.post("/api/v1/talent-imports", json=body, headers={"Idempotency-Key": key})
    assert replay.status_code == 404


def test_real_model_path_extracts_once_and_drops_unquoted_direction(api, runtime, monkeypatch):
    from intake_fixtures import RESUME_TEXT, resume_output
    from pydantic import SecretStr

    runtime[0].model_endpoint = "https://fixture.invalid/chat/completions"
    runtime[0].model_name = "fixture"
    runtime[0].model_api_key = SecretStr("fixture-key")
    calls = []
    original = httpx.Client

    def respond(request):
        calls.append(request)
        payload = resume_output()
        payload["direction_assignments"] = [
            {
                "direction_id": "backend",
                "level": "primary",
                "quote": "not in source",
                "reason": "unsupported assignment",
            }
        ]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(payload)}}],
                "usage": {"total_tokens": 100},
            },
        )

    monkeypatch.setattr(
        httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(respond), **kw)
    )
    receipt = import_text(api, RESUME_TEXT, mode="live")
    drain(runtime)
    detail = api.get(f"/api/v1/talents/{receipt['talent_id']}").json()
    assert detail["classification_state"] == "unclassified", detail
    assert len(calls) == 1
    task = api.get(f"/api/v1/tasks/{receipt['task_id']}").json()
    assert task["usage"]["tokens"] == 100
    assert task["budget"]["model_calls"]["used"] == 1


def test_unknown_external_result_cannot_be_retried_or_create_research(api, runtime, monkeypatch):
    from pydantic import SecretStr

    runtime[0].model_endpoint = "https://fixture.invalid/chat/completions"
    runtime[0].model_name = "fixture"
    runtime[0].model_api_key = SecretStr("fixture-key")
    calls = []

    def timeout(*args):
        calls.append(1)
        raise httpx.ReadTimeout("fixture timeout")

    monkeypatch.setattr(analysis, "invoke_model", timeout)
    receipt = import_text(api, "职能：后端开发", mode="live")
    drain(runtime)
    task = api.get(f"/api/v1/tasks/{receipt['task_id']}").json()
    assert task["status"] == "reconciling" and task["retryable"] is False
    response = api.post(
        f"/api/v1/tasks/{task['id']}/retry",
        json={
            "expected_revision": task["revision"],
            "reason": "尝试恢复",
        },
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert response.status_code == 409
    drain(runtime)
    assert calls == [1]


def test_category_change_withdraws_only_pending_routes_and_can_restore_same_relation(api, runtime):
    back = routing_job(api, runtime, ["backend"])
    front = routing_job(api, runtime, ["frontend"])
    receipt = import_text(api, "职能：后端开发\n也负责前端开发")
    drain(runtime)
    person = api.get(f"/api/v1/talents/{receipt['talent_id']}").json()
    original = person["applications"][0]["application_id"]
    for key, quote in [("frontend", "也负责前端开发"), ("backend", "职能：后端开发")]:
        changed = api.patch(
            f"/api/v1/talents/{person['id']}/directions",
            json={
                "expected_revision": person["revision"],
                "reason": "人工确认实际职能",
                "directions": [
                    {
                        "direction_id": key,
                        "level": "primary",
                        "quote": quote,
                        "reason": "根据本人职责归类",
                    }
                ],
            },
        )
        assert changed.status_code == 200, changed.text
        person = changed.json()
        assert {a["job_id"] for a in person["applications"]} == (
            {front} if key == "frontend" else {back}
        )
    assert person["applications"][0]["application_id"] == original
    with Session(runtime[1]) as db:
        assert all(a.screening_result == "pending" for a in db.scalars(select(Application)))
        assert db.scalar(select(func.count()).select_from(Talent)) == 1


def test_new_publication_routes_existing_talent_and_paused_job_does_not_start_research(
    api, runtime
):
    receipt = import_text(api, "职能：后端开发")
    drain(runtime)
    job_id, _ = published_job(api, runtime)
    job = api.get(f"/api/v1/jobs/{job_id}").json()
    # Explicit fixture setup creates a pending direction before the next publication.
    with Session(runtime[1]) as db, db.begin():
        db.get(IntakeJob, job_id).routing_directions = ["backend"]
    post(
        api,
        f"/jobs/{job_id}/rules/publish",
        {
            "expected_draft_revision": job["draft_revision"],
            "d01_ref": job["d01_ref"],
            "d02_ref": job["d02_ref"],
            "is_test_rule": True,
            "confirmation_note": "虚构的下一规则版本",
        },
    )
    detail = api.get(f"/api/v1/talents/{receipt['talent_id']}").json()
    assert len(detail["applications"]) == 1
    job = api.get(f"/api/v1/jobs/{job_id}").json()
    assert (
        api.patch(
            f"/api/v1/jobs/{job_id}",
            json={
                "expected_revision": job["revision"],
                "status": "paused",
            },
        ).status_code
        == 200
    )
    assert api.get(f"/api/v1/talents/{receipt['talent_id']}").json()["applications"] == []
    with Session(runtime[1]) as db:
        app = db.scalar(select(Application))
        assert app.screening_result == "pending" and app.status == "routing_inactive"


def test_known_response_recovery_does_not_extract_again(api, runtime, monkeypatch):
    from intake_fixtures import RESUME_TEXT, resume_output
    from pydantic import SecretStr

    from app.modules.intake import talents

    runtime[0].model_endpoint = "https://fixture.invalid/chat/completions"
    runtime[0].model_name = "fixture"
    runtime[0].model_api_key = SecretStr("fixture-key")
    calls = []

    def invoke(*args):
        calls.append(1)
        return {**resume_output(), "direction_assignments": []}, 100

    original = talents.finish_talent
    monkeypatch.setattr(analysis, "invoke_model", invoke)
    monkeypatch.setattr(talents, "finish_talent", lambda *args: (_ for _ in ()).throw(ValueError()))
    receipt = import_text(api, RESUME_TEXT, mode="live")
    drain(runtime)
    task = api.get(f"/api/v1/tasks/{receipt['task_id']}").json()
    assert task["status"] == "failed" and task["retryable"] is True
    monkeypatch.setattr(talents, "finish_talent", original)
    post(
        api,
        f"/tasks/{task['id']}/retry",
        {
            "expected_revision": task["revision"],
            "reason": "复用已收到响应完成内部保存",
        },
        expected=202,
    )
    drain(runtime)
    assert calls == [1]
    assert api.get(f"/api/v1/tasks/{task['id']}").json()["status"] == "completed"


def test_postgres_concurrent_import_uses_one_talent_and_one_task(api, runtime):
    from concurrent.futures import ThreadPoolExecutor

    import pytest

    if runtime[1].dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL owner row serialization")
    body = {
        "execution_mode": "mock",
        "items": [
            {
                "client_item_id": "one",
                "name": "虚构.txt",
                "text": "职能：后端开发",
            }
        ],
    }

    def submit(_):
        return api.post(
            "/api/v1/talent-imports", json=body, headers={"Idempotency-Key": uuid4().hex}
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(submit, range(2)))
    assert all(r.status_code == 202 for r in responses), [r.text for r in responses]
    items = [r.json()["items"][0] for r in responses]
    assert {x["disposition"] for x in items} == {"accepted", "duplicate"}
    assert len({x["talent_id"] for x in items}) == 1
    assert len({x["task_id"] for x in items}) == 1
