from conftest import drain, post, published_job
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.contracts import ScreeningPassedEventV11
from app.core.models import Application, Artifact, OutboxEvent, Task


def test_three_screening_branches_and_persistent_handoff(api, runtime):
    job_id, rule = published_job(api, runtime)
    batch = post(
        api,
        f"/jobs/{job_id}/resume-batches",
        {
            "execution_mode": "mock",
            "items": [
                {"client_item_id": "a", "name": "同名.txt", "text": "姓名：虚构甲\n工作年限：5"},
                {"client_item_id": "b", "name": "同名.txt", "text": "姓名：虚构乙\n工作年限：1"},
                {"client_item_id": "c", "name": "未知.txt", "text": "姓名：虚构丙\n未提及工作年限"},
            ],
        },
        expected=202,
    )
    drain(runtime)
    applications = api.get(f"/api/v1/jobs/{job_id}/applications").json()["items"]
    assert {item["screening_result"] for item in applications} == {"passed", "rejected", "unknown"}
    assert len({item["candidate_id"] for item in applications}) == 3
    with Session(runtime[1]) as db:
        events = list(
            db.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "screening.passed"))
        )
        assert len(events) == 1
        event = ScreeningPassedEventV11.model_validate(events[0].payload)
        assert event.fixture_only and event.source_modes.phone is None
        assert event.business_dedup_key == "application:" + event.application_id
        assert set(event.artifact_refs) == {f"D{n:02}" for n in range(1, 7)}
        assert event.rule_pack_ref.version == rule["version"]
    status = api.get(f"/api/v1/batches/{batch['batch_id']}").json()
    assert status["status"] == "completed"
    assert status["counts"]["completed"] == 3


def test_job_unknowns_and_incomplete_rules_block_publish(api, runtime):
    job = post(
        api, "/jobs", {"title": "虚构岗位", "company": "虚构企业", "material_text": "职责待补"}
    )
    post(
        api,
        f"/jobs/{job['id']}/analyze",
        {"expected_revision": 1, "execution_mode": "mock"},
        expected=202,
    )
    drain(runtime)
    job = api.get(f"/api/v1/jobs/{job['id']}").json()
    assert "salary" in job["unknown_fields"]
    response = api.post(
        f"/api/v1/jobs/{job['id']}/rules/publish",
        headers={"Idempotency-Key": "fixture-incomplete"},
        json={
            "expected_draft_revision": job["draft_revision"],
            "d01_ref": job["d01_ref"],
            "d02_ref": job["d02_ref"],
            "is_test_rule": True,
            "confirmation_note": "测试",
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "RULES_INCOMPLETE"
    with Session(runtime[1]) as db:
        assert not list(db.scalars(select(Application)))


def test_duplicate_content_does_not_rescreen(api, runtime):
    job_id, _ = published_job(api, runtime)
    body = {
        "execution_mode": "mock",
        "items": [{"client_item_id": "one", "name": "first.txt", "text": "工作年限：5"}],
    }
    first = post(api, f"/jobs/{job_id}/resume-batches", body, expected=202)
    drain(runtime)
    body["items"][0]["name"] = "renamed.txt"
    second = post(api, f"/jobs/{job_id}/resume-batches", body, expected=202)
    assert second["items"][0]["disposition"] == "duplicate"
    assert second["items"][0]["application_id"] == first["items"][0]["application_id"]
    with Session(runtime[1]) as db:
        assert len(list(db.scalars(select(Task).where(Task.kind == "resume_parse")))) == 1
        assert len(list(db.scalars(select(Artifact).where(Artifact.type == "D06")))) == 1


def test_display_rename_does_not_rewrite_original_job_facts(api, runtime):
    job = post(
        api, "/jobs", {"title": "原始岗位名称", "company": "虚构企业", "material_text": "职责待补"}
    )
    renamed = api.patch(
        f"/api/v1/jobs/{job['id']}", json={"expected_revision": 1, "title": "展示名称"}
    )
    assert renamed.status_code == 200
    post(
        api,
        f"/jobs/{job['id']}/analyze",
        {"expected_revision": renamed.json()["revision"], "execution_mode": "mock"},
        expected=202,
    )
    drain(runtime)
    job = api.get(f"/api/v1/jobs/{job['id']}").json()
    ref = job["d01_ref"]
    artifact = api.get(f"/api/v1/artifacts/{ref['artifact_id']}?version={ref['version']}").json()
    title = next(
        field for field in artifact["structured_content"]["fields"] if field["name"] == "title"
    )
    assert job["title"] == "展示名称" and title["value"] == "原始岗位名称"
