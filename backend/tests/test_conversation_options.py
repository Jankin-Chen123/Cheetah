from types import SimpleNamespace

from app.modules.outreach.conversation_options import enforce_duration, limits


def test_default_interview_allows_more_than_two_minutes():
    case = SimpleNamespace(session_data={})
    assert limits(case)["max_turn_seconds"] == 600
    assert limits(case)["max_seconds"] == 3600


def test_duration_stop_is_idempotent(monkeypatch):
    monkeypatch.setattr("app.modules.outreach.conversation_options.time.time", lambda: 4000)
    case = SimpleNamespace(
        session_data={"started_at": 399}, status="in_progress", stop_status="none", revision=3
    )
    enforce_duration(case)
    assert case.status == "ended"
    assert case.stop_status == "confirmed"
    assert case.revision == 4
    enforce_duration(case)
    assert case.revision == 4


def test_duration_preserves_active_interview(monkeypatch):
    monkeypatch.setattr("app.modules.outreach.conversation_options.time.time", lambda: 1000)
    case = SimpleNamespace(
        session_data={"started_at": 1}, status="in_progress", stop_status="none", revision=3
    )
    enforce_duration(case)
    assert case.status == "in_progress"
    assert case.revision == 3
