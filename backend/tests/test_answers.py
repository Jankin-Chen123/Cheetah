import pytest

from app.modules.outreach.answers import correct_answer, record_answer, request_stop
from app.modules.outreach.models import OutreachCase


def case():
    return OutreachCase(
        id="fixture",
        revision=1,
        status="waiting_conditions",
        stop_status="none",
        session_data={"current_question": {"id": "q1", "question": "职责？"}, "answers": []},
    )


def test_answer_saved_and_repeat_blocked():
    item = case()
    answer = record_answer(item, "虚构回答", 1)
    assert item.session_data["answers"][0]["id"] == answer["id"]
    assert item.session_data["decision_status"] == "pending"
    with pytest.raises(ValueError, match="VERSION_CONFLICT"):
        record_answer(item, "重复", 1)
    with pytest.raises(ValueError, match="DECISION_PENDING"):
        record_answer(item, "新回答", 2)


def test_candidate_stop_is_immediate_and_reviewer_stop_is_requested():
    item = case()
    record_answer(item, "请停止", 1)
    assert item.status == "ended" and item.stop_status == "confirmed"
    with pytest.raises(ValueError, match="INTERVIEW_STOPPED"):
        record_answer(item, "后续", 2)
    other = case()
    request_stop(other, 1)
    assert other.stop_status == "requested"
    assert other.status != "ended"


def test_stop_preempts_pending_followup_without_model():
    item = case()
    record_answer(item, "项目停止后我重新安排工作", 1)
    assert item.status == "in_progress"
    assert item.session_data["decision_status"] == "pending"
    record_answer(item, "请结束面试", item.revision)
    assert item.status == "ended"
    assert item.stop_status == "confirmed"
    assert len(item.session_data["answers"]) == 2


def test_correction_preserves_history_and_does_not_restart_call():
    item = case()
    old = record_answer(item, "原始虚构回答", 1)
    status = item.status
    revised = correct_answer(item, old["id"], "更正的虚构回答", 2, "reviewer")
    assert revised["version"] == 2 and revised["corrects_id"] == old["id"]
    assert item.session_data["answer_history"][0]["text"] == "原始虚构回答"
    assert item.session_data["answers"][0]["text"] == "更正的虚构回答"
    assert item.status == status
    with pytest.raises(ValueError, match="VERSION_CONFLICT"):
        correct_answer(item, revised["id"], "重复更正", 2, "reviewer")
