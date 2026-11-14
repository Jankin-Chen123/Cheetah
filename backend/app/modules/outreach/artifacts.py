"""Artifact version gates. Callers supply validated, evidence-backed content."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.outreach.models import OutreachArtifact, OutreachCase


def locked_case(session: Session, case_id: str, organization_id: str, owner_id: str):
    case = session.scalar(
        select(OutreachCase)
        .where(
            OutreachCase.id == case_id,
            OutreachCase.organization_id == organization_id,
            OutreachCase.owner_id == owner_id,
        )
        .with_for_update()
    )
    if case is None:
        raise LookupError("Case not found")
    return case


def save_artifact(
    session: Session,
    case: OutreachCase,
    kind: str,
    content: dict,
    provenance: dict,
    input_refs: list,
) -> OutreachArtifact:
    if kind not in {"D07", "D08", "D09", "D10"}:
        raise ValueError("Unsupported artifact type")
    previous = list(
        session.scalars(
            select(OutreachArtifact).where(
                OutreachArtifact.case_id == case.id,
                OutreachArtifact.type == kind,
            )
        )
    )
    if kind == "D10":
        evaluation = session.scalar(
            select(OutreachArtifact).where(
                OutreachArtifact.case_id == case.id,
                OutreachArtifact.type == "D09",
                OutreachArtifact.valid.is_(True),
            )
        )
        if evaluation is None or evaluation.content.get("conclusion") != "recommended":
            raise ValueError("Recommendation not eligible")
        if not any(ref.get("id") == evaluation.id for ref in input_refs):
            raise ValueError("Current evaluation reference required")
    for artifact in previous:
        artifact.valid = False
        artifact.review_status = "expired"
    artifact = OutreachArtifact(
        id=uuid4().hex,
        case_id=case.id,
        type=kind,
        version=max((item.version for item in previous), default=0) + 1,
        content=content,
        provenance=provenance,
        input_refs=input_refs,
    )
    session.add(artifact)
    session.flush()
    return artifact


def invalidate_downstream(session: Session, case: OutreachCase, corrected_type: str):
    order = ["D07", "D08", "D09", "D10"]
    affected = order[order.index(corrected_type) + 1 :]
    for artifact in session.scalars(
        select(OutreachArtifact).where(
            OutreachArtifact.case_id == case.id,
            OutreachArtifact.type.in_(affected),
            OutreachArtifact.valid.is_(True),
        )
    ):
        artifact.valid = False
        artifact.review_status = "expired"
        artifact.revision += 1


def review_report(
    report: OutreachArtifact,
    expected_version: int,
    expected_revision: int,
    action: str,
    reviewer_id: str,
    reason: str,
):
    if report.type != "D10" or not report.valid:
        raise ValueError("Report expired or unavailable")
    if report.version != expected_version or report.revision != expected_revision:
        raise ValueError("Version conflict")
    if action not in {"approve", "reject"} or not reason.strip():
        raise ValueError("Review action and reason required")
    if action == "approve" and report.content.get("client_profile", {}).get("unresolved_conflicts"):
        raise ValueError("REPORT_FACT_CONFLICT_REQUIRES_CORRECTION")
    report.review_status = "approved" if action == "approve" else "rejected"
    report.provenance = {
        **report.provenance,
        "review": {"reviewer_id": reviewer_id, "reason": reason, "version": expected_version},
    }
    report.revision += 1


def export_markdown(report: OutreachArtifact) -> str:
    if report.type != "D10" or not report.valid or report.review_status != "approved":
        raise ValueError("Report not approved or expired")
    if report.content.get("client_profile", {}).get("unresolved_conflicts"):
        raise ValueError("REPORT_FACT_CONFLICT_REQUIRES_CORRECTION")
    return report.content["content_markdown"]
