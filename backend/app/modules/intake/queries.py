from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from sqlalchemy import select

from app.core import http_models as dto
from app.core.artifacts import (
    artifact_view,
    get_application,
    get_artifact,
    get_evidence,
    get_job,
    provenance,
    visible_application_file,
)
from app.core.auth import Db, User
from app.core.errors import DomainError, not_found
from app.core.idempotency import execute
from app.core.models import Application, Artifact, AuditEntry, IntakeJob, StoredFile, Task, aware
from app.core.tasks import accepted, retryable, task_view
from app.modules.intake.router import PageNumber, PageSize, Version
from app.modules.intake.schemas import RetryInput
from app.modules.intake.service import audit, require_revision
from app.modules.intake.views import application_view, paginate

router = APIRouter(tags=["intake-resources"])
ScreeningResult = Literal["pending", "passed", "unknown", "rejected", "manual_review"]


@router.get("/applications", response_model=dto.ApplicationPage)
def list_applications(
    db: Db,
    user: User,
    page: PageNumber = 1,
    page_size: PageSize = 20,
    job_id: str | None = None,
    screening_result: ScreeningResult | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    source_scope: Literal["all", "live", "mock", "manual"] = "all",
):
    from app.modules.intake.workspace import source_filter

    query = (
        select(Application)
        .where(
            Application.status == "active",
            Application.organization_id == user.organization_id,
            visible_application_file(),
        )
        .join(IntakeJob, Application.job_id == IntakeJob.id)
        .where(IntakeJob.organization_id == user.organization_id, IntakeJob.owner_id == user.id)
    )
    if job_id:
        get_job(db, user, job_id)
        query = query.where(Application.job_id == job_id)
    if screening_result:
        query = query.where(Application.screening_result == screening_result)
    if q:
        query = query.where(Application.name.icontains(q.strip(), autoescape=True))
    query = query.where(source_filter(source_scope, Application))
    return paginate(
        db,
        query.order_by(Application.created_at.desc(), Application.id.desc()),
        page,
        page_size,
        lambda app: application_view(db, app),
    )


@router.get("/jobs/{job_id}/applications", response_model=dto.ApplicationPage)
def list_job_applications(
    job_id: str,
    db: Db,
    user: User,
    page: PageNumber = 1,
    page_size: PageSize = 20,
    screening_result: ScreeningResult | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    source_scope: Literal["all", "live", "mock", "manual"] = "all",
):
    return list_applications(db, user, page, page_size, job_id, screening_result, q, source_scope)


@router.get("/applications/{application_id}", response_model=dto.Application)
def read_application(application_id: str, db: Db, user: User):
    return application_view(db, get_application(db, user, application_id))


@router.get("/applications/{application_id}/timeline", response_model=dto.TimelinePage)
def timeline(
    application_id: str, db: Db, user: User, page: PageNumber = 1, page_size: PageSize = 20
):
    get_application(db, user, application_id)
    query = (
        select(AuditEntry)
        .where(AuditEntry.application_id == application_id)
        .order_by(AuditEntry.created_at, AuditEntry.id)
    )
    return paginate(
        db,
        query,
        page,
        page_size,
        lambda row: {
            "id": row.id,
            "type": row.action,
            "title": row.action,
            "detail": row.refs.get("reason", ""),
            "actor_type": "system" if row.actor_id == "worker" else "user",
            "actor_id": row.actor_id,
            "refs": row.refs,
            "artifact_ref": row.refs.get("d06_ref", row.refs.get("artifact_ref")),
            "created_at": aware(row.created_at),
        },
    )


@router.get("/applications/{application_id}/artifacts", response_model=dto.ArtifactPage)
def list_artifacts(
    application_id: str,
    db: Db,
    user: User,
    page: PageNumber = 1,
    page_size: PageSize = 20,
    type: Annotated[str | None, Query(pattern=r"^D(0[1-9]|10)$")] = None,
):
    application = get_application(db, user, application_id)
    query = select(Artifact).where(
        Artifact.application_id == application.id, Artifact.status != "restricted"
    )
    if type:
        query = query.where(Artifact.type == type)
    return paginate(
        db,
        query.order_by(Artifact.type, Artifact.version.desc()),
        page,
        page_size,
        lambda row: {
            key: value
            for key, value in artifact_view(db, row).items()
            if key not in {"structured_content", "content_markdown"}
        },
    )


@router.get("/artifacts/{artifact_id}", response_model=dto.Artifact)
def read_artifact(artifact_id: str, version: Version, db: Db, user: User):
    return artifact_view(
        db, get_artifact(db, user, {"artifact_id": artifact_id, "version": version})
    )


@router.get("/evidence/{evidence_id}", response_model=dto.Evidence)
def read_evidence(evidence_id: str, version: Version, db: Db, user: User):
    item = get_evidence(db, user, {"evidence_id": evidence_id, "version": version})
    return {
        "evidence_id": item.evidence_id,
        "version": item.version,
        "category": item.category,
        "source_type": item.source_type,
        "subject_type": "application" if item.application_id else "job",
        "subject_id": item.application_id or item.job_id,
        "title": item.location.get("title", item.source_type),
        "quote": item.quote,
        "location": {
            "page": None,
            "section": item.location.get("field"),
            "start_ms": None,
            "end_ms": None,
            **item.location,
        },
        "original_material_ref": {
            "file_id": get_application(db, user, item.application_id).file_id,
            "version": 1,
        }
        if item.application_id
        else None,
        "source_date": aware(item.source_date) if item.source_date else None,
        "corrects_ref": item.corrects_ref,
        "status": item.status,
        "provenance": provenance(item.source_mode),
        "public_url": item.public_url,
        "retrieved_at": aware(item.created_at),
    }


@router.get("/files/{file_id}")
def read_file(file_id: str, version: Version, db: Db, user: User):
    item = db.get(StoredFile, file_id)
    if item is None or item.status != "valid" or version != 1:
        raise not_found()
    get_job(db, user, item.job_id)
    if get_application(db, user, item.application_id).status != "active":
        raise not_found()
    return Response(
        item.data,
        media_type=item.media_type,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(item.name, safe=""),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/tasks/{task_id}", response_model=dto.Task)
def read_task(task_id: str, request: Request, db: Db, user: User):
    task = db.get(Task, task_id)
    if task is None:
        raise not_found()
    if task.kind == "talent_parse":
        from app.modules.intake.talents import get_talent

        get_talent(db, user, task.payload["talent_id"])
    else:
        get_job(db, user, task.job_id)
    if task.application_id:
        get_application(db, user, task.application_id)
    return task_view(task, request.app.state.settings, db)


@router.post("/tasks/{task_id}/retry", status_code=202, response_model=dto.TaskAccepted)
def retry_task(task_id: str, body: RetryInput, request: Request, db: Db, user: User):
    def action():
        task = db.get(Task, task_id)
        if task is None:
            raise not_found()
        if task.kind == "talent_parse":
            from app.modules.intake.talents import get_talent, lock_owner

            lock_owner(db, user.id)
            talent = get_talent(db, user, task.payload["talent_id"], lock=True)
            if talent.profile_version is not None:
                raise DomainError("PRECONDITION_NOT_MET", "人才提取已经完成")
            job = None
        else:
            job = get_job(db, user, task.job_id, lock=True)
        db.refresh(task)
        require_revision(task.revision, body.expected_revision)
        if not retryable(task, request.app.state.settings):
            raise DomainError("TASK_NOT_RETRYABLE", "该任务不可重试或需先核对外部结果")
        if task.application_id:
            application = get_application(db, user, task.application_id)
            if application.generation != task.payload["generation"]:
                raise DomainError("PRECONDITION_NOT_MET", "任务输入已经失效")
        task.status, task.error_code, task.finished_at = "queued", None, None
        child = task
        while child.payload.get("parent_task_id"):
            parent = db.get(Task, child.payload["parent_task_id"])
            if not parent or parent.payload.get("continuation_task_id") != child.id:
                raise DomainError("PRECONDITION_NOT_MET", "岗位任务链已失效")
            if parent.status == "failed":
                parent.status, parent.error_code, parent.finished_at = (
                    "waiting_conditions",
                    None,
                    None,
                )
                parent.revision += 1
            child = parent
        task.revision += 1
        if job is not None:
            audit(
                db,
                job,
                user.id,
                "task.retried",
                application_id=task.application_id,
                refs={"task_id": task.id, "reason": body.reason},
            )
        return accepted(task)

    return execute(db, user, request, body.model_dump(), 202, action)
