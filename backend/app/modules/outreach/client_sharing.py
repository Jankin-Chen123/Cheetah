"""A client-specific sharing receipt is separate from internal interview processing."""

import time
from uuid import uuid4

from app.modules.outreach.artifacts import invalidate_downstream


def set_client_context(session, case, client_company_id, candidate_client_label, expected_revision):
    if case.revision != expected_revision:
        raise ValueError("VERSION_CONFLICT")
    if not client_company_id.strip() or not candidate_client_label.strip():
        raise ValueError("CLIENT_CONTEXT_REQUIRED")
    context = {
        "client_company_id": client_company_id.strip(),
        "candidate_client_label": candidate_client_label.strip(),
        "job_id": case.job_id,
    }
    if case.session_data.get("client_context") == context:
        return
    case.session_data = {**case.session_data, "client_context": context, "client_sharing": None}
    invalidate_downstream(session, case, "D09")
    case.revision += 1


def record_client_sharing(session, case, authorized, expected_revision):
    if case.revision != expected_revision:
        raise ValueError("VERSION_CONFLICT")
    context = case.session_data.get("client_context")
    if not context:
        raise ValueError("CLIENT_CONTEXT_REQUIRED")
    receipt = {
        "receipt_id": uuid4().hex,
        "recorded_at": time.time(),
        "status": "AUTHORIZED" if authorized else "WITHDRAWN",
        "scope": dict(context),
        "actor_type": "candidate_invitation",
    }
    case.session_data = {
        **case.session_data,
        "client_sharing": receipt,
        "client_sharing_history": [*case.session_data.get("client_sharing_history", []), receipt],
    }
    if not authorized:
        invalidate_downstream(session, case, "D09")
    case.revision += 1


def require_client_sharing(case):
    context = case.session_data.get("client_context")
    receipt = case.session_data.get("client_sharing")
    if case.snapshot.get("fixture_only") and not context and not receipt:
        return
    if (
        not context
        or not receipt
        or receipt.get("status") != "AUTHORIZED"
        or receipt.get("scope") != context
        or not receipt.get("receipt_id")
    ):
        raise ValueError("CLIENT_SHARING_PERMISSION_REQUIRED")
