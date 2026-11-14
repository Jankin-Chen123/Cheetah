from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from app.core import http_models as dto
from app.core.artifacts import artifact_ref, get_artifact, get_job, save_artifact
from app.core.auth import Db, User
from app.core.errors import DomainError, not_found
from app.core.idempotency import execute
from app.core.models import Budget, IntakeJob, RulePack, new_id, utcnow
from app.core.tasks import accepted, enqueue
from app.modules.intake.schemas import (
    AnalyzeJobInput,
    CreateJobInput,
    PublishRulesInput,
    RuleContent,
    SaveRuleDraftInput,
    UpdateJobInput,
)
from app.modules.intake.service import (
    audit,
    check_mode,
    require_revision,
    rule_issues,
    validate_job_inputs,
)
from app.modules.intake.views import draft_view, job_view, paginate, rule_view

router = APIRouter(tags=["intake"])
PageNumber = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
Version = Annotated[int, Query(ge=1)]


@router.post("/jobs", status_code=201, response_model=dto.Job)
def create_job(body: CreateJobInput, request: Request, db: Db, user: User):
    def action():
        job = IntakeJob(
            **body.model_dump(),
            material_fields={
                field: getattr(body, field) for field in ("title", "company", "location", "salary")
            },
            organization_id=user.organization_id,
            owner_id=user.id,
            draft=RuleContent().model_dump(mode="json"),
        )
        db.add(job)
        db.flush()
        settings = request.app.state.settings
        db.add(
            Budget(
                job_id=job.id,
                call_limit=settings.job_model_call_limit,
                token_limit=settings.job_model_token_limit,
                search_limit=settings.job_search_call_limit,
            )
        )
        audit(db, job, user.id, "job.created")
        return job_view(db, job)

    return execute(db, user, request, body.model_dump(), 201, action)


@router.get("/jobs", response_model=dto.JobPage)
def list_jobs(
    db: Db,
    user: User,
    page: PageNumber = 1,
    page_size: PageSize = 20,
    q: Annotated[str | None, Query(max_length=100)] = None,
    status: Literal["active", "paused", "archived"] | None = None,
    rule_status: Literal[
        "draft", "published", "needs_information", "pending_confirmation", "disabled"
    ]
    | None = None,
    source_scope: Literal["all", "live", "mock", "manual"] = "all",
):
    from app.modules.intake.workspace import source_filter

    query = select(IntakeJob).where(
        IntakeJob.organization_id == user.organization_id, IntakeJob.owner_id == user.id
    )
    if q:
        query = query.where(IntakeJob.title.icontains(q.strip(), autoescape=True))
    if status:
        query = query.where(IntakeJob.status == status)
    query = query.where(source_filter(source_scope, IntakeJob))
    if rule_status == "published":
        query = query.where(IntakeJob.published_version.is_not(None))
    elif rule_status == "draft":
        query = query.where(IntakeJob.published_version.is_(None))
    elif rule_status:
        query = query.where(IntakeJob.id.is_(None))
    return paginate(
        db,
        query.order_by(IntakeJob.created_at.desc(), IntakeJob.id.desc()),
        page,
        page_size,
        lambda job: job_view(db, job),
    )


@router.get("/jobs/{job_id}", response_model=dto.Job)
def read_job(job_id: str, db: Db, user: User):
    return job_view(db, get_job(db, user, job_id))


@router.patch("/jobs/{job_id}", response_model=dto.Job)
def update_job(job_id: str, body: UpdateJobInput, db: Db, user: User):
    job = get_job(db, user, job_id, lock=True)
    require_revision(job.revision, body.expected_revision)
    for field in ("title", "status"):
        value = getattr(body, field)
        if value is not None:
            setattr(job, field, value)
    job.revision += 1
    job.updated_at = utcnow()
    audit(db, job, user.id, "job.updated", refs={"status": job.status})
    return job_view(db, job)


@router.post("/jobs/{job_id}/analyze", status_code=202, response_model=dto.TaskAccepted)
def analyze_job(job_id: str, body: AnalyzeJobInput, request: Request, db: Db, user: User):
    def action():
        job = get_job(db, user, job_id, lock=True)
        require_revision(job.revision, body.expected_revision)
        check_mode(request.app.state.settings, body.execution_mode)
        if job.status != "active":
            raise DomainError("PRECONDITION_NOT_MET", "岗位未启用")
        task = enqueue(
            db,
            organization_id=user.organization_id,
            job_id=job.id,
            kind="job_analysis",
            dedup_key=f"job:{job.id}:{job.draft_revision}:analysis",
            payload={
                "draft_revision": job.draft_revision,
                "execution_mode": body.execution_mode,
                "input_refs": [{"kind": "material", "id": job.id, "version": 1}],
            },
        )
        return accepted(task)

    return execute(db, user, request, body.model_dump(), 202, action)


@router.get("/jobs/{job_id}/rules/draft", response_model=dto.RuleDraft)
def read_draft(job_id: str, db: Db, user: User):
    return draft_view(get_job(db, user, job_id))


@router.patch("/jobs/{job_id}/rules/draft", response_model=dto.RuleDraft)
def save_draft(job_id: str, body: SaveRuleDraftInput, db: Db, user: User):
    job = get_job(db, user, job_id, lock=True)
    require_revision(job.draft_revision, body.expected_draft_revision)
    job.draft = body.content.model_dump(mode="json")
    job.draft_revision += 1
    job.revision += 1
    job.updated_at = utcnow()
    audit(db, job, user.id, "rules.draft_saved", refs={"draft_revision": job.draft_revision})
    return draft_view(job)


@router.post("/jobs/{job_id}/rules/publish", status_code=201, response_model=dto.RulePack)
def publish_rules(job_id: str, body: PublishRulesInput, request: Request, db: Db, user: User):
    def action():
        job = get_job(db, user, job_id, lock=True)
        require_revision(job.draft_revision, body.expected_draft_revision)
        issues = rule_issues(RuleContent.model_validate(job.draft))
        if issues:
            raise DomainError("RULES_INCOMPLETE", "请补充并确认规则后再发布", details=issues)
        refs = {"D01": body.d01_ref.model_dump(), "D02": body.d02_ref.model_dump()}
        validate_job_inputs(db, user, job, refs)
        upstream = [get_artifact(db, user, ref, valid=True) for ref in refs.values()]
        if not body.is_test_rule and any(
            "mock" in [a.source_mode, *a.inherited_source_modes] for a in upstream
        ):
            raise DomainError("PRECONDITION_NOT_MET", "模拟产物只能发布测试规则")
        if body.is_test_rule:
            check_mode(request.app.state.settings, "mock")
        version = (job.published_version or 0) + 1
        previous = (
            db.get(RulePack, (job.id, job.published_version)) if job.published_version else None
        )
        d02 = save_artifact(
            db,
            job,
            "D02",
            {"rules": job.draft, "confirmation_status": "confirmed"},
            source="manual",
            inherited=sorted(
                {m for a in upstream for m in [a.source_mode, *a.inherited_source_modes]}
            ),
            inputs=list(refs.values()),
        )
        rule = RulePack(
            job_id=job.id,
            version=version,
            rule_pack_id=previous.rule_pack_id if previous else new_id(),
            content=job.draft,
            d01_ref=refs["D01"],
            d02_ref=artifact_ref(d02),
            is_test_rule=body.is_test_rule,
            published_by=user.id,
        )
        db.add(rule)
        job.published_version = version
        job.draft_revision += 1
        job.revision += 1
        job.updated_at = utcnow()
        audit(
            db,
            job,
            user.id,
            "rules.published",
            refs={"version": version, "confirmation_note": body.confirmation_note},
        )
        db.flush()
        return rule_view(rule)

    return execute(db, user, request, body.model_dump(), 201, action)


@router.get("/jobs/{job_id}/rules/versions", response_model=dto.RulePackPage)
def list_rule_versions(
    job_id: str, db: Db, user: User, page: PageNumber = 1, page_size: PageSize = 20
):
    get_job(db, user, job_id)
    return paginate(
        db,
        select(RulePack).where(RulePack.job_id == job_id).order_by(RulePack.version.desc()),
        page,
        page_size,
        rule_view,
    )


@router.get("/jobs/{job_id}/rules/versions/{version}", response_model=dto.RulePack)
def read_rule_version(job_id: str, version: int, db: Db, user: User):
    get_job(db, user, job_id)
    rule = db.get(RulePack, (job_id, version))
    if rule is None:
        raise not_found()
    return rule_view(rule)
