import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.modules.outreach.followup_worker import execute_followup
from app.modules.outreach.models import ModelStep, OutreachArtifact, OutreachCase
from app.modules.outreach.steps import register_step


@pytest.mark.parametrize(
    "change", ["stop", "formal_interview", "transcription", "extraction", "evaluation", "outline"]
)
def test_followup_late_result_is_discarded(tmp_path, monkeypatch, change):
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
                snapshot={"fixture_only": True},
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
            if change == "stop":
                case.stop_status = "requested"
                case.revision += 1
            elif change != "outline":
                case.session_data = {
                    **case.session_data,
                    "processing_permissions": {change: {"status": "WITHDRAWN"}},
                }
            else:
                case.session_data = {**case.session_data, "outline_requires_regeneration": True}
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
        task = session.get(ModelStep, task_id)
        assert task.status == "cancelled"
        assert task.detail["error_code"] == {
            "stop": "INPUT_CHANGED_OR_STOPPED",
            "outline": "OUTLINE_REGENERATION_REQUIRED",
        }.get(change, "PROCESSING_PERMISSION_REQUIRED")
        assert not session.get(OutreachCase, "case").session_data.get("decisions")


def test_topic_limit_still_uses_language_understanding(tmp_path, monkeypatch):
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
                snapshot={"fixture_only": True},
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
                        {
                            "id": "Q2",
                            "question": "结果？",
                            "dimension_id": "results",
                            "method_entry_ids": ["m"],
                        }
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
    monkeypatch.setattr(
        "app.modules.outreach.followup_worker.retrieve", lambda *a, **k: [{"entry_id": "m"}]
    )

    calls = []

    def model(settings, instruction, context):
        calls.append(context["topic_limit_guidance"])
        return {"content": context["topic_limit_guidance"], "model": "fixture", "usage": None}

    monkeypatch.setattr("app.modules.outreach.followup_worker.generate_json", model)
    execute_followup(engine, Settings(), task_id)
    with Session(engine) as session:
        assert session.get(ModelStep, task_id).status == "completed"
        decision = session.get(OutreachCase, "case").session_data["decisions"][-1]
        assert decision["action"] == "next_topic"
        assert decision["generator_kind"] == "model"
        assert decision["model"] == "fixture"
        assert len(calls) == 1


def test_model_continues_without_knowledge(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'no-knowledge.db'}")
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
                snapshot={"fixture_only": True},
                session_data={
                    "decision_status": "pending",
                    "answers": [
                        {
                            "id": "a1",
                            "text": "你能解释一下个人贡献是什么意思吗？",
                            "question": {"question": "职责？", "dimension_id": "responsibility"},
                        }
                    ],
                },
            )
        )
        session.flush()
        task, _ = register_step(session, "case", "followup", 1)
        task_id = task.id
    monkeypatch.setattr("app.modules.outreach.followup_worker.retrieve", lambda *a, **k: [])
    monkeypatch.setattr(
        "app.modules.outreach.followup_worker.generate_json",
        lambda *a: {
            "content": {
                "action": "clarify",
                "question": "指您自己实际完成的工作，能举一个例子吗？",
                "dimension_id": "responsibility",
                "method_entry_ids": [],
                "answer_evidence_ids": ["a1"],
                "reason": "回应反问",
            },
            "model": "fixture",
            "usage": None,
        },
    )
    execute_followup(engine, Settings(), task_id)
    with Session(engine) as session:
        assert session.get(ModelStep, task_id).status == "completed"
        assert (
            session.get(OutreachCase, "case").session_data["decisions"][-1]["method_entry_ids"]
            == []
        )


def test_model_failure_keeps_interview_listening(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'failure.db'}")
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
                snapshot={"fixture_only": True},
                session_data={
                    "decision_status": "pending",
                    "answers": [
                        {
                            "id": "a1",
                            "text": "你能解释一下个人贡献是什么意思吗？",
                            "question": {"question": "职责？", "dimension_id": "responsibility"},
                        }
                    ],
                },
            )
        )
        session.flush()
        task, _ = register_step(session, "case", "followup", 1)
        task_id = task.id
    monkeypatch.setattr("app.modules.outreach.followup_worker.retrieve", lambda *a, **k: [])
    from app.integrations.bailian import ModelUnavailable

    def unavailable(*args):
        raise ModelUnavailable("MODEL_RESPONSE_INVALID")

    monkeypatch.setattr("app.modules.outreach.followup_worker.generate_json", unavailable)
    execute_followup(engine, Settings(), task_id)
    with Session(engine) as session:
        assert session.get(ModelStep, task_id).status == "completed"
        case = session.get(OutreachCase, "case")
        assert case.stop_status == "none"
        assert case.session_data["decision_status"] == "completed"
        assert case.session_data["decisions"][-1]["generator_kind"] == "program_clarification"
        assert (
            session.get(OutreachCase, "case").session_data["decisions"][-1]["method_entry_ids"]
            == []
        )


def test_repeated_model_question_transitions_without_failure(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'repeated.db'}")
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
                snapshot={"fixture_only": True},
                session_data={
                    "decision_status": "pending",
                    "answers": [
                        {
                            "id": "a1",
                            "text": "你能解释一下个人贡献是什么意思吗？",
                            "question": {"question": "职责？", "dimension_id": "responsibility"},
                        }
                    ],
                },
            )
        )
        session.flush()
        task, _ = register_step(session, "case", "followup", 1)
        task_id = task.id
    monkeypatch.setattr("app.modules.outreach.followup_worker.retrieve", lambda *a, **k: [])
    monkeypatch.setattr(
        "app.modules.outreach.followup_worker.generate_json",
        lambda *a: {
            "content": {
                "action": "clarify",
                "question": "职责？",
                "dimension_id": "responsibility",
                "method_entry_ids": [],
                "answer_evidence_ids": ["a1"],
                "reason": "回应反问",
            },
            "model": "fixture",
            "usage": None,
        },
    )
    execute_followup(engine, Settings(), task_id)
    with Session(engine) as session:
        assert session.get(ModelStep, task_id).status == "completed"
        assert (
            session.get(OutreachCase, "case").session_data["decisions"][-1]["method_entry_ids"]
            == []
        )

        assert (
            session.get(ModelStep, task_id).detail["metadata_adjustments"][
                "repeated_question_replaced"
            ]
            is True
        )


@pytest.mark.parametrize("remaining_required", [False, True])
def test_final_additions_acknowledgement_respects_required_questions(
    monkeypatch, remaining_required
):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        session.add(
            OutreachCase(
                id="closing",
                organization_id="org",
                owner_id="owner",
                application_id="app",
                candidate_id="candidate",
                job_id="job",
                snapshot={"fixture_only": True},
                session_data={
                    "decision_status": "pending",
                    "outline_id": "outline",
                    "answers": [
                        {
                            "id": "a1",
                            "text": "没有补充，谢谢",
                            "question": {"question": "您还有什么想补充的吗？"},
                        }
                    ],
                },
            )
        )
        session.add(
            OutreachArtifact(
                id="outline",
                case_id="closing",
                type="D07",
                version=1,
                content={
                    "questions": [
                        {
                            "id": "required",
                            "priority": "MUST",
                            "question": "你承担哪项职责？",
                            "dimension_id": "responsibility",
                        }
                    ]
                    if remaining_required
                    else [],
                },
                provenance={},
                input_refs=[],
            )
        )
        session.flush()
        task, _ = register_step(session, "closing", "followup", 1)
        task_id = task.id

    def model(*args, **kwargs):
        assert remaining_required, "Normal closing must not call inference"
        return {
            "content": {
                "action": "end",
                "reason": "模型提前结束",
            },
            "model": "fixture",
            "usage": None,
        }

    monkeypatch.setattr("app.modules.outreach.followup_worker.generate_json", model)
    execute_followup(engine, Settings(), task_id)
    with Session(engine) as session:
        case = session.get(OutreachCase, "closing")
        assert session.get(ModelStep, task_id).status == "completed"
        if remaining_required:
            assert case.status != "ended"
            assert case.session_data["current_question"]["id"] == "required"
            return
        assert case.status == "ended"
        assert case.stop_status == "none"
        assert case.session_data["termination_reason"] == "interview_completed"
