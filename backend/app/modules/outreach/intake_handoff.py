"""Consume verified intake events atomically; preparation never initiates contact."""

import hashlib
import json
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.core.errors import DomainError
from app.core.models import Artifact, IntakeJob, OutboxEvent, RulePack
from app.modules.intake.schemas import RuleContent
from app.modules.intake.service import validate_handoff
from app.modules.outreach.intake_views import outreach_content
from app.modules.outreach.job_standard import JobInterviewStandard, bind_confirmed_standard
from app.modules.outreach.models import OutreachArtifact, OutreachCase, ReceivedEvent
from app.modules.outreach.templates import ReportTemplate, snapshot


def _contents(db, event):
    result = {}
    for kind, ref in event.artifact_refs.items():
        item = db.get(Artifact, (ref.artifact_id, ref.version))
        result[kind] = {
            **outreach_content(kind, item.content),
            "artifact_id": item.artifact_id,
            "artifact_version": item.version,
            "job_id": item.job_id,
            "organization_id": item.organization_id,
            **({"candidate_id": event.candidate_id} if item.application_id else {}),
        }
    result["D01"]["title"] = db.get(IntakeJob, event.job_id).title
    return result


def _bind_published_standard(db, case, event):
    rule = db.get(RulePack, (event.job_id, event.rule_pack_ref.version))
    content = RuleContent.model_validate(rule.content)
    policy = content.recommendation_policy
    if (
        policy is None
        or policy.decision_method != "weighted_score"
        or policy.threshold is None
        or not all(d.anchors and d.weight and d.source_quotes for d in content.interview_dimensions)
    ):
        case.session_data = {**case.session_data, "standard_binding_required": True}
        return
    dimensions = []
    for dimension in content.interview_dimensions:
        anchors = dimension.anchors
        dimensions.append(
            {
                "id": dimension.id,
                "label": dimension.label,
                "indicators": dimension.rubric,
                "weight_percent": Decimal(str(dimension.weight)) * 100,
                "anchors": dict(
                    zip(
                        ("1-2", "3-4", "5-6", "7-8", "9-10"),
                        (
                            anchors.low,
                            anchors.limited,
                            anchors.partial,
                            anchors.strong,
                            anchors.excellent,
                        ),
                        strict=True,
                    )
                ),
                "source_refs": [
                    f"artifact:{rule.d02_ref['artifact_id']}:{rule.d02_ref['version']}"
                ],
            }
        )
    standard = JobInterviewStandard(
        job_id=event.job_id,
        version=rule.version,
        status="confirmed",
        confirmed_by=rule.published_by,
        dimensions=dimensions,
    )
    bind_confirmed_standard(
        db,
        case,
        standard,
        threshold=policy.threshold,
        report_template_version=1,
        expected_revision=case.revision,
        actor_id=rule.published_by,
    )


def consume_passed(db, record):
    event = validate_handoff(db, record)
    job = db.get(IntakeJob, event.job_id)
    digest = hashlib.sha256(json.dumps(record.payload, sort_keys=True).encode()).hexdigest()
    received = db.scalar(
        select(ReceivedEvent).where(
            ReceivedEvent.organization_id == event.organization_id,
            ReceivedEvent.event_id == event.event_id,
        )
    )
    if received:
        if received.payload_hash != digest:
            raise DomainError("EVENT_PAYLOAD_CONFLICT", "事件内容与已接收版本不一致")
        record.status = "delivered"
        return db.get(OutreachCase, received.case_id)
    case = db.scalar(
        select(OutreachCase)
        .where(
            OutreachCase.organization_id == event.organization_id,
            OutreachCase.application_id == event.application_id,
        )
        .with_for_update()
    )
    if case is None:
        case = OutreachCase(
            id=uuid4().hex,
            organization_id=event.organization_id,
            owner_id=job.owner_id,
            application_id=event.application_id,
            candidate_id=event.candidate_id,
            job_id=event.job_id,
            snapshot=event.model_dump(mode="json"),
            session_data={
                "answers": [],
                "attempts": [],
                "preflight_required": True,
                "upstream_content": _contents(db, event),
                "fixture_only": event.fixture_only,
            },
        )
        db.add(case)
        db.flush()
        try:
            _bind_published_standard(db, case, event)
        except ValueError:
            case.session_data = {**case.session_data, "standard_binding_required": True}
        template = ReportTemplate(
            id="cheetah-recommendation",
            version=1,
            status="approved",
            title="候选人推荐报告",
            highlights_heading="岗位匹配依据",
            unknowns_heading="待核实事项",
            disclaimer="材料和候选人自述未经独立核实；缺失信息保留未知。具体版本经人工审核后方可交付。",
        )
        case.session_data = {**case.session_data, "report_template": snapshot(template)}
    elif case.snapshot.get("artifact_refs") != event.model_dump(mode="json")["artifact_refs"]:
        # A correction cannot silently restart preparation, interviewing or delivery.
        _invalidate(db, case)
        record.status = "blocked"
        return case
    db.add(
        ReceivedEvent(
            id=uuid4().hex,
            organization_id=event.organization_id,
            event_id=event.event_id,
            payload_hash=digest,
            case_id=case.id,
        )
    )
    record.status = "delivered"
    db.flush()
    return case


def _invalidate(db, case):
    for artifact in db.scalars(
        select(OutreachArtifact).where(
            OutreachArtifact.case_id == case.id, OutreachArtifact.valid.is_(True)
        )
    ):
        artifact.valid, artifact.review_status = False, "expired"
        artifact.revision += 1
    case.session_data = {**case.session_data, "upstream_invalidated": True}
    if case.status == "in_progress" and case.stop_status == "none":
        case.stop_status = "requested"
    case.revision += 1


def consume_pending(db, limit=10):
    records = list(
        db.scalars(
            select(OutboxEvent)
            .where(
                OutboxEvent.status == "pending",
                OutboxEvent.event_type.in_(["screening.passed", "intake.invalidated"]),
            )
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    for record in records:
        if record.event_type == "intake.invalidated":
            case = db.scalar(
                select(OutreachCase)
                .where(
                    OutreachCase.organization_id == record.organization_id,
                    OutreachCase.application_id == record.application_id,
                )
                .with_for_update()
            )
            invalidated = record.payload.get("invalidated_refs", [])
            affected = case and (
                not invalidated
                or any(
                    ref in invalidated for ref in case.snapshot.get("artifact_refs", {}).values()
                )
            )
            if affected and not case.session_data.get("upstream_invalidated"):
                _invalidate(db, case)
            record.status = "delivered"
        else:
            try:
                consume_passed(db, record)
            except DomainError:
                record.status = "invalidated"
    return len(records)
