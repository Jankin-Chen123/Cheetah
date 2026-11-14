import pytest

from app.modules.outreach.interview import (
    InterviewDecision,
    Outline,
    bounded_topic_decision,
    termination_reason,
    validate_decision,
    validate_question_cards,
)


def test_question_cards_require_coverage_budget_and_real_source():
    outline = Outline.model_validate(
        {
            "questions": [
                {
                    "id": "Q1",
                    "dimension_id": "custom",
                    "question": "本人负责什么？",
                    "method_entry_ids": ["m"],
                    "evidence_target": "个人职责",
                    "planned_minutes": 26,
                    "source_refs": ["fixture-D03"],
                    "stop_rule": "已说明或无法补充即停止",
                    "conditional_followups": [
                        {"trigger": "角色不明", "question": "您负责哪部分？"}
                    ],
                }
            ]
        }
    )
    refs = {"D03": {"artifact_id": "fixture-D03", "version": 1}}
    assert validate_question_cards(outline, {"custom"}, refs) is outline
    with pytest.raises(ValueError, match="DIMENSION_COVERAGE"):
        validate_question_cards(outline, {"custom", "missing"}, refs)
    with pytest.raises(ValueError, match="QUESTION_CARDS"):
        validate_question_cards(outline, {"custom"}, {"D03": {"artifact_id": "other"}})
    outline.questions[0].planned_minutes = 25
    with pytest.raises(ValueError, match="QUESTION_CARDS"):
        validate_question_cards(outline, {"custom"}, refs)


def test_program_stop_and_limits():
    assert termination_reason("我想停止", 1, 10) == "candidate_requested_stop"
    assert termination_reason("回答", 12, 10) == "round_limit"
    assert termination_reason("回答", 1, 1200) == "duration_limit"
    assert termination_reason("回答", 1, 10) is None


def test_stop_request_distinguishes_work_history_and_negation():
    for answer in ("项目停止后我重新安排工作", "不要停止面试", "我想停止旧项目并改进流程"):
        assert termination_reason(answer, 1, 10) is None
    for answer in ("请停止", "我想停止", "请结束面试", "谢谢，请挂断电话。", "STOP INTERVIEW"):
        assert termination_reason(answer, 1, 10) == "candidate_requested_stop"


def test_decision_requires_retrieved_method_and_real_answer_reference():
    methods = [{"entry_id": "method-1"}]
    answers = [{"id": "answer-1", "text": "虚构实际输入"}]
    data = {
        "action": "clarify",
        "question": "个人贡献是什么？",
        "dimension_id": "responsibility",
        "method_entry_ids": ["method-1"],
        "answer_evidence_ids": ["answer-1"],
        "reason": "需要澄清个人贡献",
    }
    decision = InterviewDecision.model_validate(data)
    assert validate_decision(decision, methods, answers, [], {"responsibility"}) == decision
    with pytest.raises(ValueError, match="Repeated"):
        validate_decision(decision, methods, answers, ["个人贡献是什么?"], {"responsibility"})
    with pytest.raises(ValueError, match="method citation"):
        validate_decision(decision, [], answers, [], {"responsibility"})
    with pytest.raises(ValueError, match="answer evidence"):
        validate_decision(decision, methods, [], [], {"responsibility"})
    for citations in ([], ["older-answer"]):
        without_latest = decision.model_copy(update={"answer_evidence_ids": citations})
        with pytest.raises(ValueError, match="Latest answer evidence"):
            validate_decision(
                without_latest,
                methods,
                [{"id": "older-answer"}, *answers],
                [],
                {"responsibility"},
            )


def test_dimension_limit_advances_outline_without_claiming_sufficient_evidence():
    data = {
        "answers": [
            {"id": "a", "question": {"question": "职责", "dimension_id": "responsibility"}}
        ],
        "decisions": [{"action": "followup", "dimension_id": "responsibility"}] * 2,
    }
    outline = {
        "questions": [
            {"question": "结果如何核实？", "dimension_id": "results", "method_entry_ids": ["m"]}
        ]
    }
    decision = bounded_topic_decision(data, outline)
    assert decision.action == "next_topic"
    assert decision.question == "结果如何核实？"
    assert decision.answer_evidence_ids == ["a"]
    assert bounded_topic_decision(data, {"questions": []}).action == "end"
    data["decisions"] = data["decisions"][:1]
    assert bounded_topic_decision(data, outline) is None
