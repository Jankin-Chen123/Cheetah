import pytest

from app.modules.outreach.models import OutreachCase
from app.modules.outreach.preflight import (
    confirm_preflight,
    mock_briefing_email,
    record_interest,
    require_preflight,
)


def test_preflight_interest_mail_dedup_and_version_confirmation():
    case = OutreachCase(
        id="fixture",
        revision=1,
        status="waiting_conditions",
        stop_status="none",
        snapshot={"fixture_only": True},
        session_data={},
    )
    with pytest.raises(ValueError, match="INTEREST"):
        mock_briefing_email(case, "candidate@example.test", "候选人同意模拟", "intent-1")
    record_interest(case, True, "虚构候选人表示正在看机会")
    mail = mock_briefing_email(case, "candidate@example.test", "候选人同意模拟", "intent-1")
    revision = case.revision
    assert mock_briefing_email(case, "candidate@example.test", "候选人同意模拟", "intent-1") == mail
    assert case.revision == revision
    assert mail["status"] == "simulated" and mail["sent_at"] is None
    with pytest.raises(ValueError, match="CONFLICT"):
        confirm_preflight(case, "同意开始", "stale")
    confirm_preflight(case, "已了解资料且愿意开始虚构面试", mail["material_sha256"])
    assert case.session_data["preflight"]["confirmed"]
    case.session_data = {**case.session_data, "preflight_required": True}
    require_preflight(case)
    case.session_data = {
        **case.session_data,
        "upstream_content": {"D01": {"salary": "更新的虚构范围"}},
    }
    with pytest.raises(ValueError, match="BRIEFING_VERSION_CONFLICT"):
        require_preflight(case)
    record_interest(case, False, "目前不考虑机会")
    assert not case.session_data["preflight"]["confirmed"]


@pytest.mark.parametrize(
    "status,stop", [("ended", "confirmed"), ("cancelled", "none"), ("in_progress", "requested")]
)
def test_stopped_preflight_cannot_send_or_confirm(status, stop):
    case = OutreachCase(
        id="stopped",
        revision=7,
        status=status,
        stop_status=stop,
        snapshot={"fixture_only": True},
        session_data={"preflight": {"interested": True}},
    )
    for action in (
        lambda: record_interest(case, True, "愿意"),
        lambda: mock_briefing_email(case, "candidate@example.test", "同意", "one"),
        lambda: confirm_preflight(case, "同意开始", "old-material"),
    ):
        with pytest.raises(ValueError, match="INTERVIEW_STOPPED"):
            action()
    assert case.revision == 7
    assert case.session_data == {"preflight": {"interested": True}}
