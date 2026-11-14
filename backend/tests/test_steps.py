from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.modules.outreach.models import ModelStep, OutreachCase
from app.modules.outreach.steps import claim_step, finish_step, register_step, result_still_current


def test_recover_orphan_speech_but_keep_active_long_transcription():
    from app.modules.outreach.steps import recover_stale_steps

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    began = (datetime.now(UTC) - timedelta(seconds=200)).isoformat()
    with Session(engine) as session, session.begin():
        for kind in ["farewell", "transcription", "D07"]:
            session.add(
                ModelStep(
                    id=kind,
                    case_id="case",
                    step=kind,
                    input_revision=1,
                    status="running",
                    detail={"registered_at": began},
                )
            )
    with Session(engine) as session, session.begin():
        assert recover_stale_steps(session) == 1
        assert session.get(ModelStep, "farewell").status == "failed"
        assert session.get(ModelStep, "transcription").status == "running"
        assert session.get(ModelStep, "D07").status == "running"
        session.get(ModelStep, "D07").detail = {
            "started_at": (datetime.now(UTC) - timedelta(seconds=301)).isoformat()
        }
        assert recover_stale_steps(session) == 1
        assert session.get(ModelStep, "D07").status == "failed"


def test_step_dedup_and_terminal_receipt_survive_new_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        step, created = register_step(session, "fixture-case", "D07", 1)
        assert created
        same, created = register_step(session, "fixture-case", "D07", 1)
        assert not created and same.id == step.id
        finish_step(step, error_code="MODEL_NOT_CONFIGURED")
        step_id = step.id
        with pytest.raises(ValueError, match="TERMINAL"):
            finish_step(step, result_ref={"id": "invented"})
    with Session(engine) as session:
        step = session.get(ModelStep, step_id)
        assert step.status == "failed"
        assert step.detail["error_code"] == "MODEL_NOT_CONFIGURED"


def test_claim_once_and_stop_invalidates_late_result():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        case = OutreachCase(
            id="fixture",
            organization_id="org",
            owner_id="owner",
            application_id="app",
            candidate_id="candidate",
            job_id="job",
            snapshot={},
            session_data={},
        )
        session.add(case)
        session.flush()
        task, _ = register_step(session, case.id, "followup", 1)
        assert claim_step(session, task.id)["input_revision"] == 1
        assert claim_step(session, task.id) is None
        assert result_still_current(task, case)
        case.stop_status = "requested"
        case.revision += 1
        assert not result_still_current(task, case)
