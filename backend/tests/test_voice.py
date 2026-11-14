from app.modules.outreach.answers import record_answer, request_stop
from app.modules.outreach.models import OutreachCase
from app.modules.outreach.voice import confirm_mock_stop, mock_callback, start_mock


def test_simulation_dedup_order_and_stop_confirmation():
    case = OutreachCase(
        revision=1,
        status="waiting_conditions",
        stop_status="none",
        snapshot={"fixture_only": True},
        session_data={"outline_id": "d07"},
    )
    start_mock(case, 1)
    start_mock(case, 2)
    assert len(case.session_data["attempts"]) == 1
    mock_callback(case, "event-2", 2, "in_progress")
    revision = case.revision
    mock_callback(case, "event-1", 1, "completed")
    assert case.revision == revision and case.status == "in_progress"
    request_stop(case, revision)
    assert case.stop_status == "requested"
    confirm_mock_stop(case)
    assert case.stop_status == "confirmed" and case.status == "ended"
    revision = case.revision
    mock_callback(case, "late", 3, "in_progress")
    assert case.revision == revision and case.status == "ended"


def test_candidate_stop_also_stops_mock_attempt_without_model():
    case = OutreachCase(
        revision=1,
        status="waiting_conditions",
        stop_status="none",
        snapshot={"fixture_only": True},
        session_data={"outline_id": "d07", "current_question": {"id": "q1"}},
    )
    start_mock(case, 1)
    record_answer(case, "请停止", case.revision)
    assert case.stop_status == "confirmed" and case.status == "ended"
    assert case.session_data["attempts"][0]["status"] == "completed"
