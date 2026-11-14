"""Case-scoped candidate capabilities. Raw secrets are returned only on creation."""

import hashlib
import secrets
import time
from uuid import uuid4

from app.modules.outreach.models import OutreachCase


def issue_invitation(case: OutreachCase, lifetime_seconds: int = 3600):
    if case.status in {"ended", "cancelled"} or case.stop_status != "none":
        raise ValueError("INTERVIEW_STOPPED")
    if not 60 <= lifetime_seconds <= 86400:
        raise ValueError("INVITATION_LIFETIME_INVALID")
    token = secrets.token_urlsafe(32)
    invitation = {
        "id": uuid4().hex,
        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "expires_at": int(time.time()) + lifetime_seconds,
        "revoked": False,
    }
    # Reissue revokes the prior capability without retaining raw tokens.
    case.session_data = {**case.session_data, "candidate_invitation": invitation}
    case.revision += 1
    return {"id": invitation["id"], "token": token, "expires_at": invitation["expires_at"]}


def validate_invitation(case: OutreachCase, token: str):
    invitation = case.session_data.get("candidate_invitation", {})
    digest = hashlib.sha256(token.encode()).hexdigest()
    if (
        not token
        or invitation.get("revoked", True)
        or invitation.get("expires_at", 0) <= time.time()
        or not secrets.compare_digest(invitation.get("token_sha256", ""), digest)
    ):
        raise ValueError("INVITATION_INVALID")
    return invitation["id"]


def revoke_invitation(case: OutreachCase):
    invitation = case.session_data.get("candidate_invitation")
    if invitation and not invitation.get("revoked"):
        case.session_data = {
            **case.session_data,
            "candidate_invitation": {**invitation, "revoked": True},
        }
        case.revision += 1
