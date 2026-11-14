"""Transaction-scoped outreach commands; never initiates a real phone call."""

import hashlib
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.contracts import ScreeningPassedEvent
from app.modules.outreach.models import OutreachCase, ReceivedEvent


def consume_fixture(session: Session, event: ScreeningPassedEvent, owner_id: str) -> OutreachCase:
    if not event.fixture_only or not event.rule_pack_ref.is_test_rule:
        raise ValueError(
            "Only isolated fixtures are supported until upstream verification is connected"
        )
    if any(mode != "mock" for mode in event.source_modes.model_dump().values()):
        raise ValueError("Fixture sources must remain mock")
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(728195)"))
    digest = hashlib.sha256(event.model_dump_json().encode()).hexdigest()
    receipt = session.scalar(
        select(ReceivedEvent).where(
            ReceivedEvent.organization_id == event.organization_id,
            ReceivedEvent.event_id == event.event_id,
        )
    )
    if receipt:
        if receipt.payload_hash != digest:
            raise ValueError("Event ID reused with different payload")
        return session.get(OutreachCase, receipt.case_id)
    case = session.scalar(
        select(OutreachCase).where(
            OutreachCase.organization_id == event.organization_id,
            OutreachCase.application_id == event.application_id,
        )
    )
    if case is None:
        case = OutreachCase(
            id=uuid4().hex,
            organization_id=event.organization_id,
            owner_id=owner_id,
            application_id=event.application_id,
            candidate_id=event.candidate_id,
            job_id=event.job_id,
            snapshot=event.model_dump(mode="json"),
            session_data={
                "answers": [],
                "attempts": [],
                "fixture_only": True,
                "preflight_required": True,
            },
        )
        session.add(case)
        session.flush()
    session.add(
        ReceivedEvent(
            id=uuid4().hex,
            organization_id=event.organization_id,
            event_id=event.event_id,
            payload_hash=digest,
            case_id=case.id,
        )
    )
    session.flush()
    return case
