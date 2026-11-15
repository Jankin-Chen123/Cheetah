import json

from conftest import drain, post, published_job
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Artifact, OutboxEvent
from app.modules.outreach.intake_handoff import consume_pending
from app.modules.outreach.models import OutreachArtifact, OutreachCase, ReceivedEvent
from app.modules.outreach.preflight import require_preflight


def passed(api, runtime):
    job_id, _ = published_job(api, runtime)
    receipt = post(
        api,
        f"/jobs/{job_id}/resume-batches",
        {
            "execution_mode": "mock",
            "items": [
                {
                    "client_item_id": "one",
                    "name": "fiction.txt",
                    "text": "姓名：虚构测试甲\n工作年限：5",
                }
            ],
        },
        expected=202,
    )
    drain(runtime)
    return job_id, receipt["items"][0]["application_id"]


def test_verified_v11_creates_owned_case_once_without_contact(api, runtime):
    job_id, application_id = passed(api, runtime)
    owner_id = api.get("/api/v1/auth/me").json()["user"]["id"]
    with Session(runtime[1]) as db, db.begin():
        assert consume_pending(db) == 1
        case = db.scalar(select(OutreachCase))
        assert case.job_id == job_id and case.application_id == application_id
        assert case.owner_id == owner_id
        assert case.status == "waiting_conditions" and case.stop_status == "none"
        assert case.session_data["attempts"] == []
        assert case.snapshot["protocol_version"] == "1.1"
        assert case.snapshot["source_modes"]["phone"] is None
        assert case.snapshot["fixture_only"]
        assert set(case.session_data["upstream_content"]) == {f"D{i:02}" for i in range(1, 7)}
        event = db.scalar(select(OutboxEvent))
        assert event.status == "delivered"
        event.status = "pending"
        db.flush()
        assert consume_pending(db) == 1
        assert len(list(db.scalars(select(OutreachCase)))) == 1
        assert len(list(db.scalars(select(ReceivedEvent)))) == 1
    cases = api.get("/api/v1/calls").json()["items"]
    assert len(cases) == 1 and cases[0]["application_id"] == application_id
    assert (
        len(api.get("/api/v1/calls", params={"application_id": application_id}).json()["items"])
        == 1
    )
    assert (
        api.get("/api/v1/calls", params={"application_id": "another-application"}).json()["items"]
        == []
    )


def test_stale_or_restricted_upstream_never_creates_case(api, runtime):
    passed(api, runtime)
    with Session(runtime[1]) as db, db.begin():
        db.scalar(select(Artifact).where(Artifact.type == "D03")).status = "restricted"
        db.flush()
        consume_pending(db)
        assert db.scalar(select(OutreachCase)) is None
        assert db.scalar(select(OutboxEvent)).status == "invalidated"


def test_correction_expires_case_artifacts_and_blocks_continued_interview(api, runtime):
    import pytest

    from app.integrations.bailian import ModelUnavailable
    from app.modules.outreach.outline_inputs import outline_inputs

    _, application_id = passed(api, runtime)
    with Session(runtime[1]) as db, db.begin():
        consume_pending(db)
        case = db.scalar(select(OutreachCase))
        case.status = "in_progress"
        db.add(
            OutreachArtifact(
                id="old-report",
                case_id=case.id,
                type="D10",
                version=1,
                content={},
                provenance={},
                input_refs=[],
            )
        )
        db.add(
            OutboxEvent(
                organization_id=case.organization_id,
                application_id=application_id,
                event_type="intake.invalidated",
                dedup_key="correction-once",
                payload={"invalidated_refs": [case.snapshot["artifact_refs"]["D06"]]},
            )
        )
        db.flush()
        consume_pending(db)
        assert case.stop_status == "requested"
        assert not db.get(OutreachArtifact, "old-report").valid
        with pytest.raises(ValueError, match="UPSTREAM_REVIEW_REQUIRED"):
            require_preflight(case)
        with pytest.raises(ModelUnavailable, match="UPSTREAM_REVIEW_REQUIRED"):
            outline_inputs(case)


def test_old_result_invalidation_does_not_expire_case_bound_to_new_review(api, runtime):
    _, application_id = passed(api, runtime)
    with Session(runtime[1]) as db, db.begin():
        consume_pending(db)
        case = db.scalar(select(OutreachCase))
        revision = case.revision
        db.add(
            OutboxEvent(
                organization_id=case.organization_id,
                application_id=application_id,
                event_type="intake.invalidated",
                dedup_key="previous-screening-version",
                payload={"invalidated_refs": [{"artifact_id": "old-d06", "version": 1}]},
            )
        )
        db.flush()
        consume_pending(db)
        assert not case.session_data.get("upstream_invalidated")
        assert case.revision == revision and case.stop_status == "none"


def test_configured_text_provider_requires_explicit_selection(monkeypatch):
    import httpx

    from app.core.config import Settings
    from app.integrations.bailian import generate_json

    settings = Settings(
        _env_file=None,
        text_provider="configured",
        model_name="deepseek-test",
        model_endpoint="https://fixture.invalid/chat/completions",
        model_api_key="fixture-test-key",
    )
    original = httpx.Client
    requests = []

    def response(request):
        requests.append(request)
        body = json.loads(request.content)
        assert body["thinking"] == {"type": "disabled"}
        assert "fixture-test-key" not in str(body)
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]},
        )

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(response), **kwargs),
    )
    result = generate_json(settings, "Return data", {"material": "untrusted"})
    assert result["content"] == {"ok": True} and result["source_mode"] == "live"
    assert len(requests) == 1
