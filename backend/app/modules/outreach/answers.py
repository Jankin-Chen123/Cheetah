"""Persist actual text answers independently from subsequent model generation."""

import time
from uuid import uuid4

from app.modules.outreach.interview import termination_reason
from app.modules.outreach.models import OutreachCase


def record_answer(case: OutreachCase, answer: str, expected_revision: int):
    if case.revision != expected_revision:
        raise ValueError("VERSION_CONFLICT")
    if case.status in {"ended", "cancelled"} or case.stop_status != "none":
        raise ValueError("INTERVIEW_STOPPED")
    from app.modules.outreach.preflight import require_preflight

    if termination_reason(answer, 0, 0) != "candidate_requested_stop":
        require_preflight(case)
    data = case.session_data
    question = data.get("current_question")
    if not question or not answer.strip():
        raise ValueError("QUESTION_AND_ANSWER_REQUIRED")
    if (
        data.get("decision_status") == "pending"
        and termination_reason(answer, 0, 0) != "candidate_requested_stop"
    ):
        raise ValueError("DECISION_PENDING")
    now = time.time()
    answers = [
        *data.get("answers", []),
        {
            "id": uuid4().hex,
            "text": answer,
            "question": question,
            "recorded_at": now,
            "source_mode": "manual",
        },
    ]
    from app.modules.outreach.conversation_options import case_termination

    reason = case_termination(case, answer, len(answers), now - data.get("started_at", now))
    case.session_data = {
        **data,
        "answers": answers,
        "started_at": data.get("started_at", now),
        "decision_status": "stopped" if reason else "pending",
        "termination_reason": reason,
    }
    case.revision += 1
    if reason:
        case.status = "ended"
        if case.session_data.get("attempts"):
            from app.modules.outreach.voice import confirm_mock_stop

            case.stop_status = "requested"
            confirm_mock_stop(case)
        else:
            case.stop_status = "confirmed"
    else:
        case.status = "in_progress"
    return answers[-1]


def request_stop(case: OutreachCase, expected_revision: int):
    if case.revision != expected_revision:
        raise ValueError("VERSION_CONFLICT")
    if case.stop_status == "confirmed":
        return
    case.stop_status = "requested"
    case.session_data = {**case.session_data, "termination_reason": "reviewer_requested_stop"}
    case.revision += 1


def correct_answer(
    case: OutreachCase, answer_id: str, replacement: str, expected_revision: int, actor_id: str
):
    if case.revision != expected_revision:
        raise ValueError("VERSION_CONFLICT")
    if not replacement.strip():
        raise ValueError("EMPTY_CORRECTION")
    answers = [dict(answer) for answer in case.session_data.get("answers", [])]
    index = next((i for i, answer in enumerate(answers) if answer["id"] == answer_id), None)
    if index is None:
        raise LookupError("Answer not found")
    original = answers[index]
    revised = {
        **original,
        "id": uuid4().hex,
        "text": replacement,
        "version": original.get("version", 1) + 1,
        "corrects_id": answer_id,
        "recorded_at": time.time(),
        "corrected_by": actor_id,
        "source_mode": "manual",
    }
    answers[index] = revised
    history = [*case.session_data.get("answer_history", []), original]
    case.session_data = {
        **case.session_data,
        "answers": answers,
        "answer_history": history,
        "correction_requires_recompute": True,
        "dialogue_memory": [],
    }
    case.revision += 1
    return revised
