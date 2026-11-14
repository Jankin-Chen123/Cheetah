import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.contracts import ScreeningPassedEvent
from app.core.database import Base
from app.modules.outreach.models import OutreachCase, ReceivedEvent
from app.modules.outreach.service import consume_fixture


def fixture_event():
    path = Path(__file__).resolve().parents[2] / "docs/contracts/day1_screening_passed.example.json"
    return ScreeningPassedEvent.model_validate(json.loads(path.read_text(encoding="utf8")))


def test_event_and_application_dedup_survive_session_restart():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    event = fixture_event()
    with Session(engine) as session, session.begin():
        case_id = consume_fixture(session, event, "fixture-owner").id
    with Session(engine) as session, session.begin():
        assert consume_fixture(session, event, "fixture-owner").id == case_id
        next_event = event.model_copy(update={"event_id": "fixture-second-event"})
        assert consume_fixture(session, next_event, "fixture-owner").id == case_id
        assert session.scalar(select(func.count()).select_from(OutreachCase)) == 1
        assert session.scalar(select(func.count()).select_from(ReceivedEvent)) == 2
        case = session.get(OutreachCase, case_id)
        assert case.status == "waiting_conditions"
        assert case.stop_status == "none"
        assert set(case.snapshot["artifact_refs"]) == {f"D{i:02}" for i in range(1, 7)}
        assert case.session_data["attempts"] == []


def test_changed_event_and_real_input_rejected():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    event = fixture_event()
    with Session(engine) as session, session.begin():
        consume_fixture(session, event, "fixture-owner")
        with pytest.raises(ValueError, match="different payload"):
            consume_fixture(
                session, event.model_copy(update={"job_id": "changed"}), "fixture-owner"
            )
        with pytest.raises(ValueError, match="isolated fixtures"):
            consume_fixture(
                session, event.model_copy(update={"fixture_only": False}), "fixture-owner"
            )
