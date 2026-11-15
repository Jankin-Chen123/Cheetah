from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.artifacts import (
    artifact_ref,
    latest,
    merge_source_modes,
    provenance,
    require_application_file,
    visible_application_file,
)
from app.core.errors import DomainError
from app.core.models import (
    Application,
    Artifact,
    BatchItem,
    IntakeJob,
    ResumeBatch,
    RulePack,
    Task,
    aware,
)
from app.modules.intake.content import candidate_profile
from app.modules.intake.schemas import RuleContent
from app.modules.intake.service import rule_issues, rule_ref


def paginate(db: Session, query, page: int, page_size: int, view):
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    items = db.scalars(query.offset((page - 1) * page_size).limit(page_size))
    return {
        "items": [view(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def rule_view(rule: RulePack):
    return {
        **rule_ref(rule),
        "job_id": rule.job_id,
        "content": rule.content,
        "d01_ref": rule.d01_ref,
        "d02_ref": rule.d02_ref,
        "published_by": rule.published_by,
        "published_at": aware(rule.published_at),
    }


def draft_view(job: IntakeJob):
    return {
        "job_id": job.id,
        "draft_revision": job.draft_revision,
        "content": job.draft,
        "validation_issues": rule_issues(RuleContent.model_validate(job.draft)),
        "updated_at": aware(job.updated_at),
    }


def active_tasks(db: Session, job_id: str, application_id: str | None = None):
    query = select(Task.id).where(
        Task.job_id == job_id, Task.status.not_in(["completed", "failed", "cancelled"])
    )
    if application_id:
        query = query.where(Task.application_id == application_id)
    return list(db.scalars(query))


def job_view(db: Session, job: IntakeJob):
    rule = db.get(RulePack, (job.id, job.published_version)) if job.published_version else None
    d01, d02 = latest(db, job.id, "D01"), latest(db, job.id, "D02")
    return {
        "audio_transcription_ref": job.audio_transcription_ref,
        "id": job.id,
        "organization_id": job.organization_id,
        "owner_id": job.owner_id,
        "revision": job.revision,
        "title": job.title,
        "routing_directions": job.routing_directions,
        "company": job.company,
        "location": job.location,
        "salary": job.salary,
        "status": job.status,
        "material_text": job.material_text,
        "material_version": 1,
        "unknown_fields": d01.content.get("unknown_fields", [])
        if d01
        else ["salary", "probation_goals"],
        "rule_status": "published" if rule else "draft",
        "published_rule_pack_ref": rule_ref(rule) if rule else None,
        "draft_revision": job.draft_revision,
        "d01_ref": artifact_ref(d01) if d01 else None,
        "d02_ref": artifact_ref(d02) if d02 else None,
        "active_task_ids": active_tasks(db, job.id),
        "counts": {
            "applications": db.scalar(
                select(func.count())
                .select_from(Application)
                .where(
                    Application.job_id == job.id,
                    Application.organization_id == job.organization_id,
                    Application.status == "active",
                    visible_application_file(),
                )
            ),
            "pending_reports": 0,
        },
        "provenance": provenance(d01.source_mode, d01.inherited_source_modes, d01.source_modes)
        if d01
        else provenance("manual"),
        "created_at": aware(job.created_at),
        "updated_at": aware(job.updated_at),
    }


def application_view(db: Session, application: Application):
    rule = db.get(RulePack, (application.job_id, application.rule_version))
    artifacts = [
        db.get(Artifact, (ref["artifact_id"], ref["version"]))
        for ref in (rule.d01_ref, rule.d02_ref)
    ]
    artifacts += [
        latest(db, application.job_id, f"D{n:02}", application.id, valid_only=False)
        for n in range(3, 11)
    ]
    modes = sorted(
        {
            mode
            for artifact in artifacts
            if artifact
            for mode in [artifact.source_mode, *artifact.inherited_source_modes]
        }
    )
    source = "mock" if "mock" in modes else "manual"
    return {
        "id": application.id,
        "candidate_id": application.candidate_id,
        "talent_id": application.talent_id,
        "routing": application.routing,
        "job_id": application.job_id,
        "workflow_id": application.workflow_id,
        "revision": application.revision,
        "generation": application.generation,
        "candidate": candidate_profile(
            artifacts[2].content.get("facts", {}) if artifacts[2] else {}
        ),
        "stage": application.stage,
        "screening_result": application.screening_result,
        "evaluation_result": "pending",
        "summary": None,
        "gaps": application.gaps,
        "waiting_reason": {
            "code": "OUTREACH_HANDOFF_PENDING",
            "message": "初筛已通过，等待面试执行器接收当前版本",
            "missing_fields": [],
        }
        if application.screening_result == "passed"
        else {
            "code": "RECOMPUTE_REQUIRED",
            "message": "更正已保存，请显式重算内部步骤",
            "missing_fields": [],
        }
        if application.screening_result == "pending"
        and application.generation > 1
        and application.stage == "intake"
        else None,
        "rule_pack_ref": rule_ref(rule),
        "call_summary": None,
        "report_summary": None,
        "active_task_ids": active_tasks(db, application.job_id, application.id),
        "allowed_actions": ["start_screening"]
        if application.stage == "matched"
        else ["correct", "screening_review"]
        if application.status == "active"
        else [],
        "provenance": {
            **provenance(
                source, modes, merge_source_modes(*(a.source_modes for a in artifacts if a))
            ),
            "fixture_only": rule.is_test_rule or "mock" in modes,
        },
        "status": application.status,
        "created_at": aware(application.created_at),
        "updated_at": aware(application.updated_at),
        "artifact_slots": [
            {
                "type": f"D{index + 1:02}",
                "state": "available"
                if artifact and artifact.status == "valid"
                else "invalidated"
                if artifact
                else "not_executed",
                "artifact_ref": artifact_ref(artifact) if artifact else None,
                "reason": None,
            }
            for index, artifact in enumerate(artifacts)
        ],
    }


def current_batch_items(db: Session, batch_id: str):
    replaced = select(BatchItem.replaces_item_id).where(BatchItem.replaces_item_id.is_not(None))
    return select(BatchItem).where(BatchItem.batch_id == batch_id, BatchItem.id.not_in(replaced))


def batch_item_view(db: Session, item: BatchItem):
    application = db.get(Application, item.application_id) if item.application_id else None
    restricted = application is not None and application.status != "active"
    if application and not restricted:
        try:
            require_application_file(db, application)
        except DomainError:
            restricted = True
    tasks = (
        list(db.scalars(select(Task).where(Task.application_id == item.application_id)))
        if item.application_id
        else []
    )
    tasks = (
        [task for task in tasks if task.payload.get("generation") == application.generation]
        if application
        else []
    )
    failed = next((step for step in tasks if step.status in {"failed", "reconciling"}), None)
    active = next((step for step in tasks if step.status not in {"completed", "cancelled"}), None)
    if item.disposition == "invalid":
        state = "invalid"
    elif item.disposition == "duplicate":
        state = "duplicate"
    elif failed:
        state = "failed"
    elif restricted:
        state = "cancelled"
    elif application and application.screening_result != "pending":
        state = "completed"
    elif active and active.status == "queued":
        state = "queued"
    else:
        state = "processing"
    error_code = item.error_code or (failed.error_code if failed else None)
    return {
        "id": item.id,
        "batch_id": item.batch_id,
        "client_item_id": item.client_item_id,
        "revision": item.revision,
        "name": "受限材料" if restricted else item.name,
        "state": state,
        "file_ref": {"file_id": application.file_id, "version": 1}
        if application and not restricted
        else None,
        "candidate_id": application.candidate_id if application else None,
        "application_id": item.application_id,
        "task_id": failed.id if failed else active.id if active else item.task_id,
        "duplicate_of_item_id": item.duplicate_of_item_id,
        "replaces_item_id": item.replaces_item_id,
        "error": {
            "code": error_code,
            "message": "当前材料处理失败",
            "request_id": item.id,
            "details": None,
        }
        if error_code
        else None,
        "created_at": aware(item.created_at),
    }


def batch_view(db: Session, batch: ResumeBatch):
    parent = db.get(Task, batch.task_id)
    rule = db.get(RulePack, (batch.job_id, batch.rule_version))
    items = [batch_item_view(db, item) for item in db.scalars(current_batch_items(db, batch.id))]
    inherited = (
        ["mock"]
        if any(
            db.get(Application, item["application_id"]).execution_mode == "mock"
            for item in items
            if item["application_id"]
        )
        else []
    )
    counts = {
        key: 0 for key in ("queued", "processing", "completed", "failed", "duplicate", "cancelled")
    }
    for item in items:
        key = "failed" if item["state"] == "invalid" else item["state"]
        counts[key] += 1
    if counts["queued"] or counts["processing"]:
        status = "processing"
    elif counts["failed"]:
        status = "failed" if counts["failed"] == len(items) else "partial_failed"
    elif items and counts["cancelled"] == len(items):
        status = "cancelled"
    else:
        status = "completed"
    return {
        "id": batch.id,
        "job_id": batch.job_id,
        "task_id": batch.task_id,
        "status": status,
        "rule_pack_ref": rule_ref(rule),
        "counts": {"total": len(items), **counts},
        "provenance": provenance("mock" if batch.execution_mode == "mock" else "manual", inherited),
        "created_at": aware(batch.created_at),
        "updated_at": aware(parent.finished_at or parent.started_at or batch.created_at),
    }


def batch_receipt(db: Session, batch: ResumeBatch):
    items = list(db.scalars(current_batch_items(db, batch.id)))
    return {
        "batch_id": batch.id,
        "task_id": batch.task_id,
        "poll_after_ms": 3000,
        "items": [
            {
                "item_id": item.id,
                "client_item_id": item.client_item_id,
                "disposition": item.disposition,
                "application_id": item.application_id,
                "error": batch_item_view(db, item)["error"],
            }
            for item in items
        ],
    }
