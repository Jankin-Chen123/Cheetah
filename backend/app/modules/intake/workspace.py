from typing import Literal

from fastapi import APIRouter
from sqlalchemy import Text, exists, or_, select

from app.core import http_models as dto
from app.core.artifacts import get_application, provenance, visible_application_file
from app.core.auth import Db, User
from app.core.errors import DomainError
from app.core.models import Application, Artifact, IntakeJob, Task, aware, utcnow
from app.modules.intake.router import PageNumber, PageSize

router = APIRouter(tags=["workspace"])
SourceScope = Literal["all", "live", "mock", "manual"]


def source_filter(scope: str, entity):
    mock_artifact = exists(
        select(Artifact.artifact_id).where(
            Artifact.job_id == entity.id
            if entity is IntakeJob
            else Artifact.application_id == entity.id,
            or_(
                Artifact.source_mode == "mock",
                Artifact.inherited_source_modes.cast(Text).contains('"mock"'),
            ),
        )
    )
    mock = (
        mock_artifact
        if entity is IntakeJob
        else or_(Application.execution_mode == "mock", mock_artifact)
    )
    # User supplied job/resume material is manual; no intake object is pure live at this stage.
    if scope == "mock":
        return mock
    if scope == "manual":
        return ~mock
    return entity.id.is_(None) if scope == "live" else entity.id.is_not(None)


def owned_jobs(user):
    return select(IntakeJob).where(
        IntakeJob.owner_id == user.id, IntakeJob.organization_id == user.organization_id
    )


def owned_applications(user):
    return (
        select(Application)
        .join(IntakeJob, IntakeJob.id == Application.job_id)
        .where(
            IntakeJob.owner_id == user.id,
            IntakeJob.organization_id == user.organization_id,
            Application.status == "active",
            Application.organization_id == user.organization_id,
            visible_application_file(),
        )
    )


@router.get("/workspace/summary", response_model=dto.WorkspaceSummary)
def workspace_summary(db: Db, user: User, source_scope: SourceScope = "all"):
    from sqlalchemy import func

    jobs = owned_jobs(user).where(
        IntakeJob.status == "active", source_filter(source_scope, IntakeJob)
    )
    applications = owned_applications(user).where(source_filter(source_scope, Application))
    return {
        "as_of": utcnow(),
        "source_scope": source_scope,
        "active_job_count": db.scalar(select(func.count()).select_from(jobs.subquery())),
        "application_count": db.scalar(select(func.count()).select_from(applications.subquery())),
        "waiting_call_count": 0,
        "pending_report_count": 0,
        "incomplete_modules": ["outreach"],
        "outreach_summary_connected": False,
    }


@router.get("/todos", response_model=dto.TodoPage)
def todos(
    db: Db,
    user: User,
    page: PageNumber = 1,
    page_size: PageSize = 20,
    job_id: str | None = None,
    type: Literal[
        "rule_confirmation",
        "material_correction",
        "identity_ambiguity",
        "evidence_conflict",
        "screening_review",
        "report_review",
        "external_reconciliation",
        "delivered_report_correction",
    ]
    | None = None,
    source_scope: SourceScope = "all",
):
    from app.core.artifacts import get_job

    if job_id:
        get_job(db, user, job_id)
    jobs = owned_jobs(user).where(source_filter(source_scope, IntakeJob))
    applications = owned_applications(user).where(source_filter(source_scope, Application))
    if job_id:
        jobs = jobs.where(IntakeJob.id == job_id)
        applications = applications.where(Application.job_id == job_id)
    items = []

    def add(
        identifier,
        kind,
        title,
        resource_type,
        resource_id,
        job_id,
        application_id,
        created_at,
        source,
    ):
        if type and type != kind:
            return
        items.append(
            {
                "id": identifier,
                "type": kind,
                "title": title,
                "reason": {"code": kind.upper(), "message": title, "missing_fields": []},
                "resource_type": resource_type,
                "resource_id": resource_id,
                "job_id": job_id,
                "application_id": application_id,
                "created_at": aware(created_at),
                "provenance": provenance(source),
            }
        )

    for job in db.scalars(jobs):
        if not job.published_version:
            mocked = db.scalar(
                select(Artifact.artifact_id).where(
                    Artifact.job_id == job.id, Artifact.source_mode == "mock"
                )
            )
            add(
                f"rules:{job.id}",
                "rule_confirmation",
                "请确认并发布岗位标准",
                "job",
                job.id,
                job.id,
                None,
                job.created_at,
                "mock" if mocked else "manual",
            )
    for application in db.scalars(applications):
        if application.screening_result in {"unknown", "manual_review"}:
            add(
                f"screening:{application.id}:{application.revision}",
                "screening_review",
                "初筛证据不足或需人工复核",
                "application",
                application.id,
                application.job_id,
                application.id,
                application.updated_at,
                "mock" if application.execution_mode == "mock" else "manual",
            )
    visible_job_ids = select(IntakeJob.id).where(
        IntakeJob.owner_id == user.id,
        IntakeJob.organization_id == user.organization_id,
    )
    for task in db.scalars(
        select(Task).where(
            Task.job_id.in_(visible_job_ids), Task.status.in_(["failed", "reconciling"])
        )
    ):
        if task.application_id:
            try:
                get_application(db, user, task.application_id)
            except DomainError:
                continue
        if job_id and task.job_id != job_id:
            continue
        if task.kind == "batch":
            continue
        source = "mock" if task.payload.get("execution_mode") == "mock" else "manual"
        if source_scope not in {"all", source}:
            continue
        add(
            f"task:{task.id}:{task.revision}",
            "external_reconciliation" if task.status == "reconciling" else "material_correction",
            "请核对外部调用结果"
            if task.status == "reconciling"
            else "内部步骤失败，请核对依赖或材料",
            "application" if task.application_id else "job",
            task.application_id or task.job_id,
            task.job_id,
            task.application_id,
            task.finished_at or task.created_at,
            source,
        )
    items.sort(key=lambda item: (item["created_at"], item["id"]), reverse=True)
    return {
        "items": items[(page - 1) * page_size : page * page_size],
        "total": len(items),
        "page": page,
        "page_size": page_size,
    }
