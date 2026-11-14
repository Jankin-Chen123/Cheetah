import json

import pytest

from app.modules.outreach.invitations import (
    issue_invitation,
    revoke_invitation,
    validate_invitation,
)
from app.modules.outreach.models import OutreachCase
from app.modules.outreach.router import candidate_view


def test_candidate_view_excludes_internal_session_and_question_before_consent():
    case = OutreachCase(
        revision=1,
        status="waiting_conditions",
        stop_status="none",
        snapshot={"artifact_refs": {"D09": "private"}},
        session_data={
            "candidate_invitation": {"token_sha256": "secret"},
            "current_question": {"question": "private question"},
            "answers": [{"text": "private answer"}],
        },
    )
    result = candidate_view(case)
    serialized = json.dumps(result)
    assert "private" not in serialized and "secret" not in serialized
    assert "upstream_refs" not in result["material"]
    assert result["question"] is None


def test_capability_rotation_revocation_expiry_and_scope(monkeypatch):
    monkeypatch.setattr("app.modules.outreach.invitations.time.time", lambda: 1000)
    case = OutreachCase(
        id="one", revision=1, status="in_progress", stop_status="none", session_data={}
    )
    other = OutreachCase(id="two", session_data={})
    first = issue_invitation(case)
    assert first["token"] not in json.dumps(case.session_data)
    assert validate_invitation(case, first["token"]) == first["id"]
    with pytest.raises(ValueError, match="INVALID"):
        validate_invitation(other, first["token"])
    second = issue_invitation(case, 60)
    with pytest.raises(ValueError, match="INVALID"):
        validate_invitation(case, first["token"])
    monkeypatch.setattr("app.modules.outreach.invitations.time.time", lambda: 1060)
    with pytest.raises(ValueError, match="INVALID"):
        validate_invitation(case, second["token"])
    third = issue_invitation(case)
    revoke_invitation(case)
    with pytest.raises(ValueError, match="INVALID"):
        validate_invitation(case, third["token"])
    case.status = "ended"
    with pytest.raises(ValueError, match="STOPPED"):
        issue_invitation(case)
