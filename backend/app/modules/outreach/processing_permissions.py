"""Candidate-scoped permission receipts and a server-produced interview handoff."""

import time
from copy import deepcopy
from uuid import uuid4

from app.modules.outreach.artifacts import invalidate_downstream

PURPOSES = {"formal_interview", "transcription", "extraction", "evaluation"}


def record_processing_permission(session, case, purpose, authorized, expected_revision):
    if case.revision != expected_revision:
        raise ValueError("VERSION_CONFLICT")
    if purpose not in PURPOSES:
        raise ValueError("PERMISSION_PURPOSE_INVALID")
    if authorized and (case.status in {"ended", "cancelled"} or case.stop_status != "none"):
        raise ValueError("INTERVIEW_STOPPED")
    existing = case.session_data.get("processing_permissions", {}).get(purpose)
    if existing and existing.get("status") == ("AUTHORIZED" if authorized else "WITHDRAWN"):
        return existing
    receipt = {
        "receipt_id": uuid4().hex,
        "purpose": purpose,
        "status": "AUTHORIZED" if authorized else "WITHDRAWN",
        "recorded_at": time.time(),
        "actor_type": "candidate_invitation",
        "policy_version": "interview-processing.v1",
    }
    permissions = {**case.session_data.get("processing_permissions", {}), purpose: receipt}
    case.session_data = {
        **case.session_data,
        "processing_permissions": permissions,
        "processing_permission_history": [
            *case.session_data.get("processing_permission_history", []),
            receipt,
        ],
        "interview_session_id": case.session_data.get("interview_session_id") or uuid4().hex,
    }
    if not authorized:
        invalidate_downstream(session, case, "D07")
        case.session_data = {**case.session_data, "a06_session": None}
    case.revision += 1
    return receipt


def require_processing_permission(case, purpose):
    permissions = case.session_data.get("processing_permissions", {})
    # Existing fixture paths remain explicitly restricted demonstrations.
    if case.snapshot.get("fixture_only") and purpose not in permissions:
        return
    if permissions.get(purpose, {}).get("status") != "AUTHORIZED":
        raise ValueError("PROCESSING_PERMISSION_REQUIRED")


def finalize_interview_session(session, case):
    """Use submitted answer receipts, never a preparation draft or synthetic transcript."""
    from app.modules.outreach.handoff import require_extraction_session
    from app.modules.outreach.preflight import require_preflight

    answers = case.session_data.get("answers", [])
    if not answers or case.status != "ended" or case.stop_status == "requested":
        raise ValueError("FORMAL_INTERVIEW_NOT_FINISHED")
    require_preflight(case)
    permissions = case.session_data.get("processing_permissions", {})
    if any(permissions.get(purpose, {}).get("status") != "AUTHORIZED" for purpose in PURPOSES):
        raise ValueError("PROCESSING_PERMISSION_REQUIRED")
    first = answers[0].get("execution_ref") or {}
    turns = []
    for answer in answers:
        execution = answer.get("execution_ref") or {}
        transcription = answer.get("audio_transcription") or {}
        if (
            answer.get("actor_type") != "candidate_invitation"
            or not answer.get("turn_id")
            or any(
                permissions[p]["recorded_at"] > answer.get("recorded_at", 0)
                for p in ("formal_interview", "transcription")
            )
        ):
            raise ValueError("CANDIDATE_TURN_RECEIPT_REQUIRED")
        turns.append(
            {
                "answer_id": answer["id"],
                "answer_version": answer.get("version", 1),
                "text": answer["text"],
                "speaker": "candidate",
                "turn_id": answer["turn_id"],
                "question_id": answer["question"]["id"],
                "question_text": answer["question"].get("question"),
                "dimension_id": answer["question"].get("dimension_id"),
                "parent_question_id": execution.get("parent_question_id"),
                "outline_ref": execution.get("outline_ref"),
                "standard_binding": execution.get("standard_binding"),
                "recorded_at": answer["recorded_at"],
                "source_mode": answer.get("source_mode"),
                "transcription_ref": transcription.get("task_id"),
                "transcription_source_mode": transcription.get("source_mode"),
                "source_type": "MANUAL_CORRECTION"
                if answer.get("corrected_by")
                else "CANDIDATE_ORAL"
                if transcription
                else "CANDIDATE_TEXT",
            }
        )
    attempts = case.session_data.get("attempts", [])
    attempt = attempts[-1] if attempts else {}
    termination = case.session_data.get("termination_reason")
    status = "PARTIAL"
    if attempt.get("status") in {"failed", "interrupted"} and not termination:
        status = "INTERRUPTED"
    elif termination == "interview_completed":
        status = "COMPLETED"
    package = {
        "organization_id": case.organization_id,
        "job_id": case.job_id,
        "candidate_id": case.candidate_id,
        "case_id": case.id,
        "session_id": case.session_data.get("interview_session_id"),
        "interview_mode": "FORMAL_INTERVIEW",
        "termination_reason": termination,
        "call_attempt_status": attempt.get("status"),
        "call_attempt_source_mode": attempt.get("source_mode"),
        "started_at": case.session_data.get("started_at"),
        "last_answer_at": answers[-1]["recorded_at"],
        "opportunity_interest": (
            "INTERESTED"
            if case.session_data.get("preflight", {}).get("interested") is True
            else "UNKNOWN"
        ),
        "answer_source_modes": sorted(
            {turn["source_mode"] for turn in turns if turn["source_mode"]}
        ),
        "status": status,
        "permissions": deepcopy(permissions),
        "executed_outline": first.get("outline_ref"),
        "executed_standard": first.get("standard_binding"),
        "answer_turns": turns,
        "source_mode": "mock" if case.snapshot.get("fixture_only") else "manual",
    }
    review = case.session_data.get("outline_readiness_review")
    executed_outline = package["executed_outline"] or {}
    if review and executed_outline == {
        "id": review.get("outline_id"),
        "version": review.get("outline_version"),
    }:
        package["outline_readiness_review"] = deepcopy(review)
    previous = case.session_data.get("a06_session")
    case.session_data = {**case.session_data, "a06_session": package}
    try:
        require_extraction_session(session, case)
    except ValueError:
        case.session_data = {**case.session_data, "a06_session": previous}
        raise
    return package
