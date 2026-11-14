"""Repeatable development practice creates isolated cases, never revives a terminal case."""

import copy
import hashlib
import hmac
import time

from app.core.contracts import ScreeningPassedEvent
from app.modules.outreach.artifacts import save_artifact
from app.modules.outreach.conversation_options import PRACTICE_LIMITS, voice_id
from app.modules.outreach.invitations import validate_invitation
from app.modules.outreach.models import OutreachArtifact
from app.modules.outreach.service import consume_fixture
from app.modules.outreach.voice import start_mock


def create_practice(session, source, request_id, bearer_token, settings):
    if settings.environment != "development" or not source.snapshot.get("fixture_only"):
        raise ValueError("PRACTICE_FIXTURE_ONLY")
    invitation_id = validate_invitation(source, bearer_token)
    outline = session.get(OutreachArtifact, source.session_data.get("outline_id", ""))
    if not outline or outline.case_id != source.id or not outline.valid:
        raise ValueError("PRACTICE_OUTLINE_REQUIRED")
    receipts = source.session_data.get("practice_requests", {})
    receipt_key = invitation_id + ":" + request_id
    if receipt_key not in receipts and len(receipts) >= 50:
        raise ValueError("PRACTICE_SESSION_LIMIT")
    digest = hashlib.sha256(f"{source.id}:{receipt_key}".encode()).hexdigest()[:32]
    payload = copy.deepcopy(source.snapshot)
    for key in ("event_id", "application_id", "candidate_id"):
        payload[key] = "practice-" + key + "-" + digest
    case = consume_fixture(session, ScreeningPassedEvent.model_validate(payload), source.owner_id)
    token = hmac.new(
        bearer_token.encode(), (source.id + receipt_key).encode(), hashlib.sha256
    ).hexdigest()
    if receipt_key in receipts:
        validate_invitation(case, token)
        return case, token
    artifact = save_artifact(
        session,
        case,
        "D07",
        copy.deepcopy(outline.content),
        {
            **copy.deepcopy(outline.provenance),
            "generator_kind": "reused_outline",
            "reused_from": {"id": outline.id, "version": outline.version},
        },
        [{"kind": "artifact", "id": outline.id, "version": outline.version}],
    )
    invitation = {
        "id": digest,
        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "expires_at": min(
            int(time.time()) + 86400, source.session_data["candidate_invitation"]["expires_at"]
        ),
        "revoked": False,
    }
    case.session_data = {
        **case.session_data,
        "upstream_content": copy.deepcopy(source.session_data.get("upstream_content", {})),
        "outline_id": artifact.id,
        "current_question": copy.deepcopy(outline.content["questions"][0]),
        "knowledge_preview": outline.content.get("knowledge_preview", False),
        "voice_id": voice_id(source),
        "candidate_invitation": invitation,
        "interview_limits": PRACTICE_LIMITS,
        "practice_parent_id": source.id,
    }
    for key in ("evaluation_template", "report_template"):
        if key in source.session_data:
            case.session_data = {**case.session_data, key: copy.deepcopy(source.session_data[key])}
    start_mock(case, case.revision)
    source.session_data = {
        **source.session_data,
        "practice_requests": {**receipts, receipt_key: case.id},
    }
    return case, token
