"""Recoverable post-interview dependency scheduling; never approves or exports."""

from sqlalchemy import select

from app.modules.outreach.models import OutreachArtifact, OutreachCase
from app.modules.outreach.steps import register_step


def schedule_postprocessing(session):
    registered = 0
    cases = session.scalars(
        select(OutreachCase).where(OutreachCase.status == "ended").with_for_update(skip_locked=True)
    )
    for case in cases:
        if (
            case.stop_status == "requested"
            or not case.session_data.get("answers")
            or case.session_data.get("correction_requires_recompute")
        ):
            continue
        artifacts = list(
            session.scalars(select(OutreachArtifact).where(OutreachArtifact.case_id == case.id))
        )
        current = {artifact.type: artifact for artifact in artifacts if artifact.valid}
        if "D08" not in current:
            # Existing invalid results require an explicit recompute, not an automatic restart.
            if any(artifact.type == "D08" for artifact in artifacts):
                continue
            step = "D08"
        elif "D09" not in current:
            if any(artifact.type == "D09" for artifact in artifacts):
                continue
            step = "D09"
        elif current["D09"].content.get("conclusion") == "recommended" and "D10" not in current:
            if any(artifact.type == "D10" for artifact in artifacts):
                continue
            step = "D10"
        else:
            continue
        task, created = register_step(session, case.id, step, case.revision)
        if created:
            task.detail = {
                **task.detail,
                "trigger": "interview_ended",
                "actor_id": case.owner_id,
                "organization_id": case.organization_id,
                "knowledge_preview": case.session_data.get("knowledge_preview", False),
            }
            registered += 1
    return registered
