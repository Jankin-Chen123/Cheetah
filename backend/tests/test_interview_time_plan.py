import pytest

from app.modules.outreach.interview import Outline, allocate_question_minutes


def test_topic_transition_covers_unasked_dimension_and_recognizes_prefixed_question():
    from app.modules.outreach.interview import answered_outline_ids, prefer_unasked_dimension

    planned = [
        {"id": "q1", "question": "请介绍负责的模块？", "dimension_id": "d1"},
        {"id": "q2", "question": "请解释采购流程？", "dimension_id": "d2"},
    ]
    answers = [
        {
            "id": "a1",
            "question": {
                "id": "followup-1",
                "question": "好的，我们换个话题：请介绍负责的模块？",
                "dimension_id": "d1",
            },
        }
    ]
    assert answered_outline_ids(answers, planned) == {"q1"}
    result = prefer_unasked_dimension(
        {"action": "next_topic", "dimension_id": "d1"}, answers, planned
    )
    assert result["dimension_id"] == "d2" and result["question"] == planned[1]["question"]
    assert (
        prefer_unasked_dimension({"action": "followup", "dimension_id": "d1"}, answers, planned)
        is None
    )


def test_declarative_acknowledgement_continues_without_inventing_evidence():
    from app.modules.outreach.interview import continue_after_acknowledgement

    answers = [
        {
            "id": "a1",
            "text": "时间待协商",
            "question": {"question": "多久到岗？", "dimension_id": "d1"},
        }
    ]
    planned = [{"id": "q2", "question": "请说明你的协作分工？", "dimension_id": "d2"}]
    result = continue_after_acknowledgement(
        {"action": "clarify", "question": "好的，已记录，我会保留待核实。"}, answers, planned
    )
    assert result["question"] == planned[0]["question"] and result["dimension_id"] == "d2"
    assert result["answer_evidence_ids"] == ["a1"] and answers[0]["text"] == "时间待协商"
    assert (
        continue_after_acknowledgement(
            {"action": "followup", "question": "你希望怎么协作？"}, answers, planned
        )
        is None
    )
    assert (
        continue_after_acknowledgement(
            {"action": "end", "question": "谢谢参与。"}, answers, planned
        )
        is None
    )
    assert (
        continue_after_acknowledgement(
            {"action": "clarify", "question": "岗位材料未说明出差安排，需招聘方确认。"},
            [{**answers[0], "text": "请问这个岗位出差吗？"}],
            planned,
        )
        is None
    )


@pytest.mark.parametrize("count", [1, 7, 12])
def test_program_time_slots_preserve_questions_and_sources(count):
    outline = Outline(
        questions=[
            {
                "id": str(i),
                "dimension_id": str(i),
                "question": "请说明本人职责？",
                "evidence_target": "个人职责",
                "source_refs": ["actual-artifact"],
                "planned_minutes": 4,
            }
            for i in range(count)
        ]
    )
    allocated = allocate_question_minutes(outline)
    assert sum(q.planned_minutes for q in allocated.questions) == 26
    assert all(q.planned_minutes > 0 for q in allocated.questions)
    for before, after in zip(outline.questions, allocated.questions, strict=True):
        assert before.model_dump(exclude={"planned_minutes"}) == after.model_dump(
            exclude={"planned_minutes"}
        )
        assert before.planned_minutes == 4
