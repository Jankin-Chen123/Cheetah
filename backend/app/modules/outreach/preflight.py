"""Persisted pre-interview consent; mock mail never contacts a mail server."""

import hashlib
import time
from uuid import uuid4

from app.modules.outreach.models import OutreachCase


def record_interest(case: OutreachCase, interested: bool, statement: str):
    if case.status in {"ended", "cancelled"} or case.stop_status != "none":
        raise ValueError("INTERVIEW_STOPPED")
    if not statement.strip():
        raise ValueError("CANDIDATE_STATEMENT_REQUIRED")
    prior = case.session_data.get("preflight", {})
    state = {
        **prior,
        "version": prior.get("version", 0) + 1,
        "interested": interested,
        "interest_statement": statement,
        "confirmed": False,
        "recorded_at": time.time(),
        "source_mode": "manual",
    }
    case.session_data = {**case.session_data, "preflight": state}
    case.revision += 1
    return state


def briefing_snapshot(case: OutreachCase):
    upstream = case.session_data.get("upstream_content", {})
    job = upstream.get("D01", {})
    content = {
        "job_title": job.get("title"),
        "requirements": job.get("responsibilities", []),
        "salary": job.get("salary"),
        "company_introduction": job.get("company_introduction"),
        "unknowns": job.get("unknowns", []),
        "upstream_refs": case.snapshot.get("artifact_refs", {}),
    }
    return content


def mock_briefing_email(case: OutreachCase, email: str, consent: str, request_id: str):
    if case.status in {"ended", "cancelled"} or case.stop_status != "none":
        raise ValueError("INTERVIEW_STOPPED")
    state = dict(case.session_data.get("preflight", {}))
    if state.get("interested") is not True:
        raise ValueError("JOB_INTEREST_REQUIRED")
    if not case.snapshot.get("fixture_only"):
        raise ValueError("MOCK_FIXTURE_REQUIRED")
    if not email.endswith(".test") or "@" not in email or any(c in email for c in "\r\n"):
        raise ValueError("FICTIONAL_EMAIL_REQUIRED")
    if not consent.strip() or not request_id.strip():
        raise ValueError("EMAIL_CONSENT_AND_REQUEST_REQUIRED")
    material = briefing_snapshot(case)
    import json

    digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    mails = list(state.get("emails", []))
    for mail in mails:
        if mail["request_id"] == request_id:
            if mail["recipient"] != email or mail["material_sha256"] != digest:
                raise ValueError("EMAIL_REQUEST_REUSED")
            return mail
    mail = {
        "id": uuid4().hex,
        "request_id": request_id,
        "recipient": email,
        "consent": consent,
        "material": material,
        "material_sha256": digest,
        "status": "simulated",
        "source_mode": "mock",
        "sent_at": None,
        "recorded_at": time.time(),
    }
    state.update(emails=[*mails, mail], confirmed=False)
    case.session_data = {**case.session_data, "preflight": state}
    case.revision += 1
    return mail


def confirm_preflight(case: OutreachCase, statement: str, material_sha256: str):
    if case.status in {"ended", "cancelled"} or case.stop_status != "none":
        raise ValueError("INTERVIEW_STOPPED")
    import json

    state = dict(case.session_data.get("preflight", {}))
    if state.get("interested") is not True or not statement.strip():
        raise ValueError("JOB_INTEREST_AND_CONFIRMATION_REQUIRED")
    material = briefing_snapshot(case)
    digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    if digest != material_sha256:
        raise ValueError("BRIEFING_VERSION_CONFLICT")
    state.update(
        confirmed=True,
        confirmation_statement=statement,
        material=material,
        material_sha256=digest,
        confirmed_at=time.time(),
    )
    case.session_data = {**case.session_data, "preflight": state}
    case.revision += 1
    return state


def require_preflight(case: OutreachCase):
    if case.session_data.get("preflight", {}).get("interested") is False:
        raise ValueError("JOB_INTEREST_REQUIRED")
    if case.session_data.get("preflight_required"):
        state = case.session_data.get("preflight", {})
        if state.get("interested") is not True or state.get("confirmed") is not True:
            raise ValueError("PREINTERVIEW_CONFIRMATION_REQUIRED")
        import json

        current = hashlib.sha256(
            json.dumps(briefing_snapshot(case), sort_keys=True).encode()
        ).hexdigest()
        if state.get("material_sha256") != current:
            raise ValueError("BRIEFING_VERSION_CONFLICT")
