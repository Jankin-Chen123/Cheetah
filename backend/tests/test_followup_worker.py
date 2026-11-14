from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.modules.outreach.followup_worker import execute_followup
from app.modules.outreach.models import ModelStep, OutreachArtifact, OutreachCase
from app.modules.outreach.steps import register_step


def test_followup_late_result_is_discarded_after_stop(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'followup.db'}")
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
                session_data={
                    "decision_status": "pending",
                    "answers": [
                        {"id": "a1", "text": "虚构回答", "question": {"question": "原问题"}}
                    ],
                },
            )
        )
        session.flush()
        task, _ = register_step(session, "case", "followup", 1)
        task_id = task.id
    monkeypatch.setattr(
        "app.modules.outreach.followup_worker.retrieve", lambda *a, **k: [{"entry_id": "m1"}]
    )

    def model(*args):
        with Session(engine) as session, session.begin():
            case = session.get(OutreachCase, "case")
            case.stop_status = "requested"
            case.revision += 1
        return {
            "model": "isolated-test-double",
            "usage": None,
            "content": {
                "action": "clarify",
                "question": "个人职责？",
                "dimension_id": "responsibility",
                "method_entry_ids": ["m1"],
                "answer_evidence_ids": ["a1"],
                "reason": "证据缺口",
            },
        }

    monkeypatch.setattr("app.modules.outreach.followup_worker.generate_json", model)
    execute_followup(engine, Settings(), task_id)
    with Session(engine) as session:
        assert session.get(ModelStep, task_id).status == "cancelled"
        assert not session.get(OutreachCase, "case").session_data.get("decisions")


def test_program_topic_limit_skips_model_and_budget(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'topic.db'}")
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
                session_data={
                    "outline_id": "outline",
                    "decision_status": "pending",
                    "answers": [
                        {
                            "id": "a",
                            "text": "实际回答",
                            "question": {"question": "职责？", "dimension_id": "responsibility"},
                        }
                    ],
                    "decisions": [{"action": "followup", "dimension_id": "responsibility"}] * 2,
                },
            )
        )
        session.add(
            OutreachArtifact(
                id="outline",
                case_id="case",
                type="D07",
                version=1,
                content={
                    "questions": [
                        {"question": "结果？", "dimension_id": "results", "method_entry_ids": ["m"]}
                    ],
                    "retrieved_methods": [{"entry_id": "m"}],
                },
                provenance={},
                input_refs=[],
            )
        )
        session.flush()
        task, _ = register_step(session, "case", "followup", 1)
        task_id = task.id
    monkeypatch.setattr("app.modules.outreach.followup_worker.retrieve", lambda *a, **k: [])

    def unexpected(*args):
        raise AssertionError("program topic limit must not call or reserve a model")

    monkeypatch.setattr("app.modules.outreach.followup_worker.generate_json", unexpected)
    monkeypatch.setattr("app.modules.outreach.followup_worker.reserve_model_request", unexpected)
    execute_followup(engine, Settings(), task_id)
    with Session(engine) as session:
        assert session.get(ModelStep, task_id).status == "completed"
        decision = session.get(OutreachCase, "case").session_data["decisions"][-1]
        assert decision["action"] == "next_topic"
        assert decision["generator_kind"] == "program_topic_limit"
        assert decision["model"] is None
