from conftest import drain, post, published_job
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.artifacts import artifact_ref
from app.core.models import Artifact, OutboxEvent


def test_correction_expires_results_and_explicit_recompute_preserves_mock(api, runtime):
    job_id, rule = published_job(api, runtime)
    batch = post(
        api,
        f"/jobs/{job_id}/resume-batches",
        {
            "execution_mode": "mock",
            "items": [{"client_item_id": "one", "name": "虚构.txt", "text": "工作年限：5"}],
        },
        expected=202,
    )
    drain(runtime)
    app_id = batch["items"][0]["application_id"]
    with Session(runtime[1]) as db:
        d03 = db.scalar(
            select(Artifact).where(Artifact.application_id == app_id, Artifact.type == "D03")
        )
        ref = artifact_ref(d03)
    response = post(
        api,
        f"/applications/{app_id}/corrections",
        {
            "target_artifact_ref": ref,
            "changes": [
                {
                    "path": "/facts/years_experience",
                    "value": {"value": 1, "status": "stated", "quote": "人工核实：工作年限为 1"},
                    "reason": "测试更正",
                },
                {
                    "path": "/facts/name",
                    "value": {"value": "更正虚构姓名", "status": "stated", "quote": "更正虚构姓名"},
                    "reason": "测试姓名更正",
                },
            ],
            "evidence_refs": [],
            "reason": "虚构材料更正验证",
        },
    )
    new_ref = response["new_artifact_ref"]
    assert new_ref["version"] == 2 and len(response["invalidated_artifact_refs"]) == 4
    assert (
        api.get(f"/api/v1/artifacts/{ref['artifact_id']}?version=1").json()["status"] == "expired"
    )
    with Session(runtime[1]) as db:
        old_event = db.scalar(
            select(OutboxEvent).where(OutboxEvent.event_type == "screening.passed")
        )
        assert old_event.status == "invalidated"
        assert len(list(db.scalars(select(Artifact).where(Artifact.type == "D06")))) == 1
    application = api.get(f"/api/v1/applications/{app_id}").json()
    assert application["screening_result"] == "pending"
    assert application["candidate"]["display_name"] == "更正虚构姓名"
    matches = api.get("/api/v1/applications?q=更正虚构姓名").json()
    assert matches["total"] == 1 and matches["items"][0]["id"] == app_id
    post(
        api,
        f"/applications/{app_id}/recompute",
        {
            "expected_revision": application["revision"],
            "correction_id": response["correction_id"],
            "target_steps": ["research", "screening"],
            "rule_pack_ref": {
                key: rule[key]
                for key in ("rule_pack_id", "version", "publication_status", "is_test_rule")
            },
            "reason": "明确重算内部流程",
        },
        expected=202,
    )
    drain(runtime)
    application = api.get(f"/api/v1/applications/{app_id}").json()
    assert application["screening_result"] == "rejected"
    assert application["provenance"]["fixture_only"]
    with Session(runtime[1]) as db:
        assert not list(
            db.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.status == "pending", OutboxEvent.event_type == "screening.passed"
                )
            )
        )
        latest = db.scalar(
            select(Artifact)
            .where(Artifact.application_id == app_id, Artifact.type == "D03")
            .order_by(Artifact.version.desc())
        )
        assert "mock" in latest.inherited_source_modes
