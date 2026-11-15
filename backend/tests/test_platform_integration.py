from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.core.models import Identity, LoginSession, utcnow
from app.modules.outreach.models import ModelStep, OutreachCase


def test_shared_login_isolates_intake_interviews_and_task_routes(api, runtime, monkeypatch):
    engine = runtime[1]

    def factory(request):
        return Session(engine)

    monkeypatch.setattr("app.core.auth.database_session", factory)
    monkeypatch.setattr("app.modules.outreach.router.database_session", factory)
    with Session(engine) as db, db.begin():
        owner = db.scalar(select(Identity).where(Identity.username == "fixture-owner"))
        other = db.scalar(select(Identity).where(Identity.username == "fixture-colleague"))
        owner_id = owner.id
        for case_id, user in [("mine", owner), ("other", other)]:
            db.add(
                OutreachCase(
                    id=case_id,
                    organization_id=user.organization_id,
                    owner_id=user.id,
                    application_id=case_id,
                    candidate_id=case_id,
                    job_id="fixture-job",
                    snapshot={"artifact_refs": {}, "fixture_only": True},
                    session_data={},
                )
            )
            db.add(
                ModelStep(
                    id=case_id,
                    case_id=case_id,
                    step="D07",
                    input_revision=1,
                    status="queued",
                    detail={},
                )
            )
    assert [item["id"] for item in api.get("/api/v1/calls").json()["items"]] == ["mine"]
    assert api.get("/api/v1/interview-tasks/mine").json()["resource_type"] == "call"
    assert api.get("/api/v1/tasks/mine").status_code == 404
    assert api.get("/api/v1/interview-tasks/other").status_code == 404
    assert api.get("/api/v1/calls/other").status_code == 404
    response = api.post(
        "/api/v1/calls/mine/cancel",
        json={"expected_revision": 1},
        headers={"X-CSRF-Token": "invalid"},
    )
    assert response.status_code == 403
    with Session(engine) as db, db.begin():
        db.get(Identity, owner_id).enabled = False
    assert api.get("/api/v1/auth/me").status_code == 401
    assert api.get("/api/v1/calls").status_code == 401
    with Session(engine) as db, db.begin():
        db.get(Identity, owner_id).enabled = True
        login = db.scalar(select(LoginSession).where(LoginSession.user_id == owner_id))
        login.expires_at = utcnow() - timedelta(seconds=1)
    assert api.get("/api/v1/auth/me").status_code == 401
    assert api.get("/api/v1/calls").status_code == 401


@pytest.mark.parametrize("start", [None, "0004_talent_routing", "0005_model_steps"])
def test_upgrade_from_either_branch_preserves_business_data_and_unifies_sessions(tmp_path, start):
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    engine = create_engine("sqlite:///" + str(tmp_path / "merge.sqlite"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        if start:
            command.upgrade(config, start)
        if start == "0005_model_steps":
            connection.execute(
                text(
                    "INSERT INTO login_sessions VALUES "
                    "('old-token', 'old-csrf', 'old-owner', 'old-org', 1900000000)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO outreach_cases VALUES "
                    "('case', 'org', 'owner', 'app', 'person', 'job', 1, "
                    "'waiting_conditions', 'none', '{}', '{}')"
                )
            )
        if start == "0004_talent_routing":
            connection.execute(
                text(
                    "INSERT INTO identities VALUES "
                    "('owner', 'org', 'existing-user', 'Existing', 'hash', true)"
                )
            )
        command.upgrade(config, "head")
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == (
            "0007_audio_transcriptions"
        )
        assert {c["name"] for c in inspect(connection).get_columns("login_sessions")} == {
            "token_hash",
            "user_id",
            "expires_at",
        }
        if start == "0005_model_steps":
            assert (
                connection.execute(
                    text("SELECT user_id FROM legacy_outreach_login_sessions")
                ).scalar()
                == "old-owner"
            )
            assert connection.execute(text("SELECT id FROM outreach_cases")).scalar() == "case"
            assert connection.execute(text("SELECT count(*) FROM login_sessions")).scalar() == 0
        if start == "0004_talent_routing":
            assert (
                connection.execute(text("SELECT username FROM identities")).scalar()
                == "existing-user"
            )
    engine.dispose()
