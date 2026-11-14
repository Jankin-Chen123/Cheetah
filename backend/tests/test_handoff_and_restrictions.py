import copy

import pytest
from conftest import drain, post, published_job
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.core.models import Application, Artifact, Identity, IntakeJob, OutboxEvent, StoredFile
from app.modules.intake.service import validate_handoff


def passed_pair(api, runtime):
    job_id, _ = published_job(api, runtime)
    batch = post(
        api,
        f"/jobs/{job_id}/resume-batches",
        {
            "execution_mode": "mock",
            "items": [
                {"client_item_id": "one", "name": "虚构一.txt", "text": "工作年限：5"},
                {"client_item_id": "two", "name": "虚构二.txt", "text": "工作年限：6"},
            ],
        },
        expected=202,
    )
    drain(runtime)
    return job_id, batch


def test_handoff_checks_current_owner_identity_and_candidate_specific_evidence(api, runtime):
    _, batch = passed_pair(api, runtime)
    with Session(runtime[1]) as db:
        events = list(
            db.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "screening.passed"))
        )
        assert len(events) == 2
        validate_handoff(db, events[0])
        payload = copy.deepcopy(events[0].payload)
        payload["evidence_refs"] = events[1].payload["evidence_refs"]
        forged = OutboxEvent(
            id=events[0].id,
            organization_id=events[0].organization_id,
            application_id=events[0].application_id,
            status="pending",
            payload=payload,
        )
        with pytest.raises(DomainError, match="PRECONDITION_NOT_MET"):
            validate_handoff(db, forged)
        owner = db.scalar(select(Identity).where(Identity.username == "fixture-owner"))
        owner.enabled = False
        with pytest.raises(DomainError, match="PRECONDITION_NOT_MET"):
            validate_handoff(db, events[0])


@pytest.mark.parametrize("restriction_target", ["application", "file"])
def test_restricted_application_blocks_historical_reads_and_worker_inputs(
    api, runtime, restriction_target
):
    job_id, batch = passed_pair(api, runtime)
    app_id = batch["items"][0]["application_id"]
    with Session(runtime[1]) as db, db.begin():
        application = db.get(Application, app_id)
        artifact = db.scalar(
            select(Artifact).where(Artifact.application_id == app_id, Artifact.type == "D03")
        )
        paths = [
            f"/applications/{app_id}",
            f"/artifacts/{artifact.artifact_id}?version=1",
            f"/evidence/{artifact.evidence_refs[0]['evidence_id']}?version=1",
            f"/files/{application.file_id}?version=1",
        ]
        if restriction_target == "application":
            application.status = "restricted"
        else:
            db.get(StoredFile, application.file_id).status = "restricted"
        event = db.scalar(
            select(OutboxEvent).where(
                OutboxEvent.application_id == app_id, OutboxEvent.event_type == "screening.passed"
            )
        )
        with pytest.raises(DomainError, match="PRECONDITION_NOT_MET"):
            validate_handoff(db, event)
    for path in paths:
        assert api.get("/api/v1" + path).status_code == 404
    assert api.get(f"/api/v1/jobs/{job_id}/applications").json()["total"] == 1
    assert api.get(f"/api/v1/jobs/{job_id}").json()["counts"]["applications"] == 1
    assert api.get("/api/v1/workspace/summary").json()["application_count"] == 1
    items = api.get(f"/api/v1/batches/{batch['batch_id']}/items").json()["items"]
    restricted = next(item for item in items if item["application_id"] == app_id)
    assert restricted["name"] == "受限材料" and restricted["file_ref"] is None
    repeat = post(
        api,
        f"/jobs/{job_id}/resume-batches",
        {
            "execution_mode": "mock",
            "items": [{"client_item_id": "again", "name": "renamed.txt", "text": "工作年限：5"}],
        },
        expected=202,
    )
    assert repeat["items"][0]["disposition"] == "invalid"
    assert repeat["items"][0]["application_id"] is None


def test_restricted_original_file_prevents_background_model_use_of_cached_text(
    api, runtime, monkeypatch
):
    job_id, _ = published_job(api, runtime)
    batch = post(
        api,
        f"/jobs/{job_id}/resume-batches",
        {
            "execution_mode": "mock",
            "items": [{"client_item_id": "one", "name": "虚构.txt", "text": "工作年限：5"}],
        },
        expected=202,
    )
    app_id = batch["items"][0]["application_id"]
    with Session(runtime[1]) as db, db.begin():
        db.get(StoredFile, db.get(Application, app_id).file_id).status = "restricted"
    calls = []

    def forbidden(*args):
        calls.append(1)
        raise AssertionError("Restricted material must not reach a model")

    monkeypatch.setattr("app.worker.analysis.mock_analysis", forbidden)
    drain(runtime)
    assert not calls
    assert api.get("/api/v1/todos?type=material_correction").json()["total"] == 0
    with Session(runtime[1]) as db:
        assert not list(db.scalars(select(Artifact).where(Artifact.application_id == app_id)))


def test_shared_writer_preserves_upstream_mock_without_caller_supplied_tags(api, runtime):
    from app.core.artifacts import artifact_ref, save_artifact

    job_id, batch = passed_pair(api, runtime)
    app_id = batch["items"][0]["application_id"]
    with Session(runtime[1]) as db, db.begin():
        job = db.scalar(select(IntakeJob).where(IntakeJob.id == job_id).with_for_update())
        application = db.get(Application, app_id)
        upstream = db.scalar(
            select(Artifact).where(Artifact.application_id == app_id, Artifact.type == "D03")
        )
        profile = db.scalar(
            select(Artifact).where(Artifact.application_id == app_id, Artifact.type == "D05")
        )
        derived = save_artifact(
            db,
            job,
            "D05",
            profile.content,
            application=application,
            source="live",
            inputs=[{"kind": "artifact", "id": upstream.artifact_id, "version": upstream.version}],
            evidence=upstream.evidence_refs,
        )
        ref = artifact_ref(derived)
        assert "mock" in derived.inherited_source_modes
    read = api.get(f"/api/v1/artifacts/{ref['artifact_id']}?version={ref['version']}").json()
    assert read["provenance"]["source_mode"] == "live" and read["provenance"]["fixture_only"]
