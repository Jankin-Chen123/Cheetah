"""Persisted simulation transitions; no real telephone execution."""

from uuid import uuid4

from app.integrations.voice.adapters import MockVoice
from app.modules.outreach.models import OutreachCase


def start_mock(case: OutreachCase, expected_revision: int):
    if case.revision != expected_revision:
        raise ValueError("VERSION_CONFLICT")
    if not case.snapshot.get("fixture_only") or not case.session_data.get("outline_id"):
        raise ValueError("MOCK_FIXTURE_AND_OUTLINE_REQUIRED")
    if case.session_data.get("attempts"):
        return
    if case.stop_status != "none" or case.status in {"ended", "cancelled"}:
        raise ValueError("CALL_STOPPED")
    attempt_id = uuid4().hex
    result = MockVoice().create_call(attempt_id)
    case.session_data = {
        **case.session_data,
        "attempts": [
            {
                "id": attempt_id,
                "external_request_id": attempt_id,
                "external_session_id": result["session_id"],
                "status": result["status"],
                "source_mode": "mock",
                "last_callback_sequence": 0,
                "callback_ids": [],
            }
        ],
    }
    case.status = "in_progress"
    case.revision += 1


def mock_callback(case: OutreachCase, callback_id: str, sequence: int, status: str):
    attempts = case.session_data.get("attempts", [])
    if not attempts:
        raise ValueError("NO_CALL_ATTEMPT")
    attempt = dict(attempts[-1])
    if callback_id in attempt["callback_ids"] or sequence <= attempt["last_callback_sequence"]:
        return
    if status not in {"in_progress", "completed", "interrupted", "failed"}:
        raise ValueError("INVALID_CALLBACK_STATUS")
    if attempt["status"] in {"completed", "interrupted", "failed"}:
        return
    attempt.update(
        status=status,
        last_callback_sequence=sequence,
        callback_ids=[*attempt["callback_ids"], callback_id],
    )
    case.session_data = {**case.session_data, "attempts": [*attempts[:-1], attempt]}
    if status in {"completed", "interrupted", "failed"}:
        case.status = "ended"
        if case.stop_status == "requested":
            case.stop_status = "confirmed"
    case.revision += 1


def confirm_mock_stop(case: OutreachCase):
    if case.stop_status != "requested":
        raise ValueError("STOP_NOT_REQUESTED")
    attempts = case.session_data.get("attempts", [])
    if attempts:
        attempt = dict(attempts[-1])
        result = MockVoice().stop_call(attempt["external_session_id"])
        attempt["status"] = result["status"]
        case.session_data = {**case.session_data, "attempts": [*attempts[:-1], attempt]}
    case.stop_status = "confirmed"
    case.status = "ended"
    case.revision += 1
