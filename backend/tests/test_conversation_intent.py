import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.modules.outreach.conversation_worker import execute_conversation
from app.modules.outreach.models import ModelStep, OutreachCase
from app.modules.outreach.steps import register_step


@pytest.mark.parametrize(
    ("intent", "introduced", "interested", "confirmed"),
    [
        ("interest_yes", False, True, False),
        ("confirm_yes", False, True, False),
        ("interest_yes", True, True, True),
        ("question", False, None, False),
        ("unclear", False, None, False),
    ],
)
def test_model_intent_respects_introduction_stage(
    tmp_path, monkeypatch, intent, introduced, interested, confirmed
):
    engine = create_engine(f"sqlite:///{tmp_path / 'intent.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db, db.begin():
        db.add(
            OutreachCase(
                id="fixture",
                organization_id="fixture",
                owner_id="fixture",
                application_id="fixture",
                candidate_id="fixture",
                job_id="fixture",
                snapshot={},
                session_data={
                    "conversation_utterance": "明确的虚构测试原话",
                    "voice_clarification": True,
                    "preflight": {
                        "interested": True if introduced else None,
                        "briefing_presented": introduced,
                        "confirmed": False,
                    },
                    "decision_status": "pending",
                },
            )
        )
        db.flush()
        task, _ = register_step(db, "fixture", "conversation", 1)
        task_id = task.id
    monkeypatch.setattr(
        "app.modules.outreach.conversation_worker.generate_json",
        lambda *a: {"content": {"intent": intent, "reply": "回应候选人。"}, "model": "fixture"},
    )
    execute_conversation(engine, Settings(), task_id)
    with Session(engine) as db:
        state = db.get(OutreachCase, "fixture").session_data["preflight"]
        assert state["interested"] is interested
        assert state["confirmed"] is confirmed
        assert db.get(ModelStep, task_id).status == "completed"
        assert db.get(OutreachCase, "fixture").session_data["voice_clarification"] is None
