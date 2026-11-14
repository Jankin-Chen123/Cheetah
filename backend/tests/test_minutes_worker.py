from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.modules.outreach.minutes_worker import execute_minutes
from app.modules.outreach.models import ModelStep, OutreachArtifact, OutreachCase
from app.modules.outreach.steps import register_step


def test_minutes_discarded_after_concurrent_answer_change(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'minutes.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        session.add(
            OutreachCase(
                id="case",
                organization_id="org",
                owner_id="owner",
                application_id="app",
                candidate_id="candidate",
                job_id="job",
                snapshot={},
                session_data={"answers": [{"id": "a1", "text": "原回答", "question": {}}]},
            )
        )
        session.flush()
        task, _ = register_step(session, "case", "D08", 1)
        task_id = task.id

    def model(*args):
        with Session(engine) as session, session.begin():
            case = session.get(OutreachCase, "case")
            case.revision += 1
            case.session_data = {"answers": [{"id": "a2", "text": "更正回答", "question": {}}]}
        return {
            "model": "isolated-test-double",
            "usage": None,
            "content": {
                "facts": [
                    {"statement": "原回答", "quote": "原回答", "answer_id": "a1", "kind": "other"}
                ]
            },
        }

    monkeypatch.setattr("app.modules.outreach.minutes_worker.generate_json", model)
    execute_minutes(engine, Settings(), task_id)
    with Session(engine) as session:
        assert session.get(ModelStep, task_id).status == "cancelled"
        assert session.scalar(select(func.count()).select_from(OutreachArtifact)) == 0
