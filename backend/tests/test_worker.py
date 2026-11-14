import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.modules.outreach.models import ModelStep, OutreachArtifact, OutreachCase
from app.modules.outreach.steps import register_step
from app.modules.outreach.worker import execute_outline


@pytest.mark.parametrize("stop_during_model", [False, True])
def test_outline_worker_releases_transaction_and_rechecks_stop(
    tmp_path, monkeypatch, stop_during_model
):
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.db'}")
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
                snapshot={"artifact_refs": {}},
                session_data={"upstream_content": {"fixture_only": True}},
            )
        )
        session.flush()
        task, _ = register_step(session, "case", "D07", 1)
        task_id = task.id
    monkeypatch.setattr(
        "app.modules.outreach.worker.retrieve", lambda *a, **k: [{"entry_id": "m1"}]
    )

    def model(settings, instruction, context):
        with Session(engine) as session, session.begin():
            assert session.get(ModelStep, task_id).status == "running"
            case = session.get(OutreachCase, "case")
            if stop_during_model:
                case.stop_status = "requested"
                case.revision += 1
        return {
            "model": "isolated-test-double",
            "usage": None,
            "content": {
                "questions": [
                    {
                        "id": "q1",
                        "dimension_id": "responsibility",
                        "question": "虚构问题？",
                        "method_entry_ids": ["m1"],
                        "evidence_target": "个人职责",
                    }
                ]
            },
        }

    monkeypatch.setattr("app.modules.outreach.worker.generate_json", model)
    execute_outline(engine, Settings(), task_id)
    with Session(engine) as session:
        task = session.get(ModelStep, task_id)
        assert task.status == ("cancelled" if stop_during_model else "completed")
        assert session.scalar(select(func.count()).select_from(OutreachArtifact)) == (
            0 if stop_during_model else 1
        )
