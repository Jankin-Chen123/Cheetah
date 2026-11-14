import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.modules.outreach.followup_worker import execute_followup
from app.modules.outreach.models import ModelStep, OutreachCase
from app.modules.outreach.steps import register_step
from app.modules.outreach.understanding import MemoryFact, TurnUnderstanding


def case_task(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'first.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db, db.begin():
        db.add(
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
                        {
                            "id": "a1",
                            "text": "实际虚构回答",
                            "question": {"question": "原问题？", "dimension_id": "responsibility"},
                        }
                    ],
                },
            )
        )
        db.flush()
        task, _ = register_step(db, "case", "followup", 1)
        return engine, task.id


def test_understanding_precedes_semantic_search_and_generation(tmp_path, monkeypatch):
    engine, task_id = case_task(tmp_path)
    from app.modules.outreach.models import OutreachArtifact

    with Session(engine) as db, db.begin():
        case = db.get(OutreachCase, "case")
        case.session_data = {**case.session_data, "outline_id": "outline"}
        db.add(
            OutreachArtifact(
                id="outline",
                case_id="case",
                type="D07",
                version=1,
                content={"questions": [{"question": "原问题？"}]},
                provenance={},
                input_refs=[],
            )
        )
    calls = []
    monkeypatch.setattr("app.modules.outreach.followup_worker.retrieve", lambda *a, **k: [])

    def understand(*args):
        calls.append("understand")
        assert args[1]["outline_questions"] == [{"question": "原问题？"}]
        return TurnUnderstanding(
            intent="answer",
            needs_retrieval=True,
            search_query="完整上下文意图",
            memory=[
                MemoryFact(key="count", text="实际访谈12位", answer_id="a1", status="corrected")
            ],
        ), {
            "model": "fixture",
            "working_memory": [
                {"key": "count", "text": "实际访谈12位"},
                {"key": "role", "text": "此前说明负责整理访谈提纲"},
            ],
        }

    def search(settings, query, candidates):
        assert query == "完整上下文意图"
        calls.append("search")
        return [], {"mode": "hybrid"}

    def generate(*args):
        calls.append("generate")
        assert len(args[2]["working_memory"]) == 2
        assert args[2]["working_memory"][1]["key"] == "role"
        return {
            "content": {
                "action": "followup",
                "question": "访谈之后您输出了什么？",
                "reason": "补充成果",
            },
            "model": "fixture",
            "usage": None,
        }

    monkeypatch.setattr("app.modules.outreach.understanding.understand_turn", understand)
    monkeypatch.setattr("app.modules.outreach.retrieval.hybrid_rank", search)
    monkeypatch.setattr("app.modules.outreach.followup_worker.generate_json", generate)
    execute_followup(engine, Settings(dialogue_understanding_enabled=True), task_id)
    assert calls == ["understand", "search", "generate"]
    with Session(engine) as db:
        assert db.get(ModelStep, task_id).status == "completed"
        assert (
            db.get(OutreachCase, "case").session_data["dialogue_memory"][0]["text"]
            == "实际访谈12位"
        )


def test_counterquestion_can_reply_without_search_or_second_model(tmp_path, monkeypatch):
    engine, task_id = case_task(tmp_path)
    monkeypatch.setattr("app.modules.outreach.followup_worker.retrieve", lambda *a, **k: [])
    monkeypatch.setattr(
        "app.modules.outreach.understanding.understand_turn",
        lambda *a: (
            TurnUnderstanding(
                intent="question", response="岗位材料未说明出差安排，需要招聘方确认。"
            ),
            {"model": "fixture", "usage": None},
        ),
    )

    def unexpected(*args):
        raise AssertionError("Direct response must not search or invoke another model")

    monkeypatch.setattr("app.modules.outreach.retrieval.hybrid_rank", unexpected)
    monkeypatch.setattr("app.modules.outreach.followup_worker.generate_json", unexpected)
    execute_followup(engine, Settings(dialogue_understanding_enabled=True), task_id)
    with Session(engine) as db:
        case = db.get(OutreachCase, "case")
        assert case.session_data["decisions"][-1]["generator_kind"] == "model_direct_response"
        assert db.get(ModelStep, task_id).detail["retrieval"]["mode"] == "not_needed"


@pytest.mark.parametrize("intent", ["answer", "stop"])
def test_no_matching_knowledge_reuses_understanding_reply(tmp_path, monkeypatch, intent):
    engine, task_id = case_task(tmp_path)
    monkeypatch.setattr("app.modules.outreach.followup_worker.retrieve", lambda *a, **k: [])
    monkeypatch.setattr(
        "app.modules.outreach.understanding.understand_turn",
        lambda *a: (
            TurnUnderstanding(
                intent=intent,
                needs_retrieval=intent == "answer",
                search_query="跨团队项目",
                response="您当时具体协调了哪些事项？",
            ),
            {"model": "fixture", "usage": None},
        ),
    )
    monkeypatch.setattr(
        "app.modules.outreach.retrieval.hybrid_rank", lambda *a: ([], {"mode": "none"})
    )

    def unexpected(*args):
        raise AssertionError("No second generation needed")

    monkeypatch.setattr("app.modules.outreach.followup_worker.generate_json", unexpected)
    execute_followup(engine, Settings(dialogue_understanding_enabled=True), task_id)
    with Session(engine) as db:
        case = db.get(OutreachCase, "case")
        assert db.get(ModelStep, task_id).status == "completed"
        if intent == "stop":
            assert case.status == "ended"
            assert case.session_data["termination_reason"] == "candidate_requested_stop"
        else:
            assert case.session_data["current_question"]["question"] == "您当时具体协调了哪些事项？"


def test_memory_correction_replaces_old_value_and_rejects_unknown_source(monkeypatch):
    from app.modules.outreach.understanding import understand_turn

    monkeypatch.setattr(
        "app.modules.outreach.understanding.generate_json",
        lambda *a: {
            "content": {
                "intent": "correction",
                "needs_retrieval": False,
                "response": "已改为12位。",
                "memory": [
                    {
                        "key": "count",
                        "text": "12位",
                        "answer_id": "a2",
                        "quote": "12位",
                        "status": "corrected",
                    },
                    {"key": "unsupported", "text": "不可信内容", "answer_id": "unknown"},
                ],
            },
            "model": "fixture",
        },
    )
    plan, info = understand_turn(
        Settings(),
        {
            "answers": [
                {"id": "a1", "text": "20位", "question": {"question": "多少位？"}},
                {"id": "a2", "text": "改为12位", "question": {"question": "核实数量"}},
            ],
            "dialogue_memory": [{"key": "count", "text": "20位", "answer_id": "a1"}],
        },
    )
    assert len(info["working_memory"]) == 1
    assert info["working_memory"][0]["text"] == "12位"
    assert info["working_memory"][0]["answer_id"] == "a2"
    assert len(plan.memory) == 1


def test_knowledge_revoked_during_generation_is_not_cited(tmp_path, monkeypatch):
    engine, task_id = case_task(tmp_path)
    method = {"entry_id": "m1", "content": {"topic": "贡献"}, "source": {"version": 1}}
    reads = []

    def eligible(*args, **kwargs):
        reads.append(True)
        return [method] if len(reads) == 1 else []

    monkeypatch.setattr("app.modules.outreach.followup_worker.retrieve", eligible)
    monkeypatch.setattr(
        "app.modules.outreach.understanding.understand_turn",
        lambda *a: (
            TurnUnderstanding(intent="answer", needs_retrieval=True, search_query="个人贡献"),
            {"model": "fixture"},
        ),
    )
    monkeypatch.setattr(
        "app.modules.outreach.retrieval.hybrid_rank", lambda *a: ([method], {"mode": "hybrid"})
    )
    monkeypatch.setattr(
        "app.modules.outreach.followup_worker.generate_json",
        lambda *a: {
            "content": {
                "action": "followup",
                "question": "引用已撤销的方法？",
                "method_entry_ids": ["m1"],
                "reason": "方法追问",
            },
            "model": "fixture",
            "usage": None,
        },
    )
    execute_followup(engine, Settings(dialogue_understanding_enabled=True), task_id)
    with Session(engine) as db:
        task = db.get(ModelStep, task_id)
        assert task.detail["degraded_reason"] == "KNOWLEDGE_CHANGED_DURING_INFERENCE"
        assert db.get(OutreachCase, "case").session_data["decisions"][-1]["method_entry_ids"] == []
