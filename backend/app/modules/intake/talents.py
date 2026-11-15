"""Independent, owned talent intake; direction routing does not decide qualification."""

import hashlib
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core import http_models as dto
from app.core.artifacts import artifact_ref, get_application, latest
from app.core.auth import Db, User
from app.core.errors import DomainError, not_found
from app.core.idempotency import execute
from app.core.models import (
    Application,
    Budget,
    Identity,
    IntakeJob,
    RulePack,
    StoredFile,
    Talent,
    TalentProfile,
    Task,
    aware,
    new_id,
    utcnow,
)
from app.core.tasks import accepted, enqueue
from app.modules.intake.analysis import parse_file
from app.modules.intake.batches import receive_items
from app.modules.intake.directions import (
    DIRECTIONS,
    TAXONOMY_VERSION,
    DirectionAssignment,
    DirectionId,
    compatible_directions,
)
from app.modules.intake.resume_profiles import prepare_profile, save_application_profile
from app.modules.intake.router import PageNumber, PageSize
from app.modules.intake.schemas import Input, ResumeProfile, RetryInput
from app.modules.intake.service import audit, check_mode, queue_step, require_revision
from app.modules.intake.views import paginate

router = APIRouter(tags=["talent-pool"])


class TalentLink(BaseModel):
    application_id: str
    job_id: str
    job_title: str
    stage: str
    screening_result: str
    profile_version: int
    direction_ids: list[DirectionId]


class DirectionOption(BaseModel):
    id: DirectionId
    label: str


class DirectionCatalog(BaseModel):
    version: int
    items: list[DirectionOption]


class TalentView(BaseModel):
    id: str
    revision: int
    name: str
    filename: str
    profile_version: int | None
    classification_state: Literal[
        "processing", "classified", "unclassified", "failed", "reconciling"
    ]
    directions: list[DirectionAssignment]
    classification_source: Literal["model", "mock", "manual"] | None
    task_id: str
    task_status: str
    error_code: str | None
    execution_mode: Literal["live", "mock"]
    applications: list[TalentLink]
    created_at: dto.AwareDatetime


class TalentPage(BaseModel):
    items: list[TalentView]
    total: int
    page: int
    page_size: int


class TalentDetail(TalentView):
    profile: ResumeProfile | None


class TalentReceiptItem(BaseModel):
    client_item_id: str
    name: str
    disposition: Literal["accepted", "duplicate", "invalid"]
    talent_id: str | None = None
    task_id: str | None = None
    error_code: str | None = None


class TalentReceipt(BaseModel):
    items: list[TalentReceiptItem]


class ClassifyTalentInput(Input):
    expected_revision: int = Field(ge=1)
    directions: list[DirectionAssignment] = Field(max_length=18)
    reason: str = Field(min_length=1, max_length=2000)


class RematchInput(Input):
    expected_revision: int = Field(ge=1)


def lock_owner(db, owner_id):
    db.scalar(select(Identity).where(Identity.id == owner_id).with_for_update())


def get_talent(db, user, talent_id, *, lock=False):
    query = select(Talent).where(
        Talent.id == talent_id,
        Talent.organization_id == user.organization_id,
        Talent.owner_id == user.id,
        Talent.status == "active",
    )
    if lock:
        query = query.with_for_update()
    talent = db.scalar(query.execution_options(populate_existing=True))
    if talent is None:
        raise not_found()
    return talent


def talent_context(db, task):
    talent = db.get(Talent, task.payload["talent_id"])
    if talent is None or talent.organization_id != task.organization_id:
        raise DomainError("PRECONDITION_NOT_MET", "人才材料已不可访问")
    lock_owner(db, talent.owner_id)
    owner = db.get(Identity, talent.owner_id)
    if not owner or not owner.enabled or owner.organization_id != task.organization_id:
        raise DomainError("PERMISSION_DENIED", "任务所属账号已不可用", 403)
    talent = get_talent(db, owner, talent.id, lock=True)
    if talent.task_id != task.id or talent.profile_version is not None:
        raise DomainError("PRECONDITION_NOT_MET", "人才提取任务输入已变化")
    return talent


def talent_view(db, talent, *, detail=False):
    task = db.get(Task, talent.task_id)
    profile = (
        db.get(TalentProfile, (talent.id, talent.profile_version))
        if talent.profile_version
        else None
    )
    links = []
    for app in db.scalars(
        select(Application)
        .where(
            Application.talent_id == talent.id,
            Application.status == "active",
        )
        .order_by(Application.created_at, Application.id)
    ):
        job = db.get(IntakeJob, app.job_id)
        file = db.get(StoredFile, app.file_id)
        if (
            job
            and job.owner_id == talent.owner_id
            and job.organization_id == talent.organization_id
            and file
            and file.status == "valid"
        ):
            links.append(
                {
                    "application_id": app.id,
                    "job_id": job.id,
                    "job_title": job.title,
                    "stage": app.stage,
                    "screening_result": app.screening_result,
                    "profile_version": app.routing["profile_version"],
                    "direction_ids": app.routing["direction_ids"],
                }
            )
    state = (
        ("classified" if profile.directions else "unclassified")
        if profile
        else (
            "failed"
            if task.status in {"failed", "cancelled"}
            else "reconciling"
            if task.status == "reconciling"
            else "processing"
        )
    )
    result = {
        "id": talent.id,
        "revision": talent.revision,
        "name": talent.name,
        "filename": talent.filename,
        "profile_version": talent.profile_version,
        "classification_state": state,
        "directions": profile.directions if profile else [],
        "classification_source": profile.classification_source if profile else None,
        "task_id": task.id,
        "task_status": task.status,
        "error_code": task.error_code,
        "execution_mode": talent.execution_mode,
        "applications": links,
        "created_at": aware(talent.created_at),
    }
    if detail:
        result["profile"] = profile.content if profile else None
    return result


def route_to_job(db, talent, profile, job):
    directions = compatible_directions(profile.directions, job.routing_directions)
    if (
        not directions
        or job.status != "active"
        or job.published_version is None
        or job.organization_id != talent.organization_id
        or job.owner_id != talent.owner_id
    ):
        return
    rule = db.get(RulePack, (job.id, job.published_version))
    if rule is None or (talent.execution_mode == "mock" and not rule.is_test_rule):
        return
    existing = db.scalar(
        select(Application).where(
            Application.job_id == job.id,
            Application.material_hash == talent.material_hash,
        )
    )
    if existing and (
        existing.talent_id != talent.id or existing.status not in {"active", "routing_inactive"}
    ):
        # Exact-file legacy associations are not silently merged into a new identity.
        return
    if existing:
        if existing.stage != "matched":
            return
        file = db.get(StoredFile, existing.file_id)
        if not file or file.status != "valid":
            return
        app = existing
        if app.routing.get("profile_version") == profile.version:
            if app.status != "active" or app.routing.get("direction_ids") != directions:
                app.status = "active"
                app.routing = {
                    **app.routing,
                    "direction_ids": directions,
                    "job_directions": job.routing_directions,
                }
                app.revision += 1
                app.updated_at = utcnow()
            return
        app.status = "active"
        app.generation += 1
    else:
        app = Application(
            id=new_id(),
            candidate_id=talent.id,
            talent_id=talent.id,
            organization_id=talent.organization_id,
            job_id=job.id,
            material_hash=talent.material_hash,
            name=talent.name,
            material_text=talent.material_text,
            file_id=new_id(),
            rule_version=rule.version,
            execution_mode=talent.execution_mode,
            stage="matched",
        )
        db.add(app)
        db.flush()
        db.add(
            StoredFile(
                id=app.file_id,
                organization_id=talent.organization_id,
                job_id=job.id,
                application_id=app.id,
                name=talent.filename,
                media_type=talent.media_type,
                data=talent.data,
                sha256=talent.material_hash,
            )
        )
        db.flush()
    app.routing = {
        "taxonomy_version": TAXONOMY_VERSION,
        "profile_version": profile.version,
        "direction_ids": directions,
        "classification_source": profile.classification_source,
        "job_directions": job.routing_directions,
    }
    save_application_profile(
        db,
        job,
        app,
        profile.content,
        talent.execution_mode,
        start_research=False,
        pool_ref={"talent_id": talent.id, "version": profile.version},
    )
    audit(
        db,
        job,
        talent.owner_id,
        "talent.routed",
        application_id=app.id,
        refs={"talent_id": talent.id, **app.routing},
    )


def suspend_unrelated_pending(db, *, talent_id=None, job_id=None):
    query = select(Application).where(
        Application.talent_id.is_not(None),
        Application.stage == "matched",
        Application.status == "active",
    )
    if talent_id:
        query = query.where(Application.talent_id == talent_id)
    if job_id:
        query = query.where(Application.job_id == job_id)
    for app in db.scalars(query):
        talent = db.get(Talent, app.talent_id)
        job = db.get(IntakeJob, app.job_id)
        profile = db.get(TalentProfile, (talent.id, talent.profile_version))
        if (
            job.status != "active"
            or not profile
            or not compatible_directions(profile.directions, job.routing_directions)
        ):
            # Withdraw a routing relation, not a person's opportunity or screening result.
            app.status = "routing_inactive"
            app.revision += 1
            app.updated_at = utcnow()


def route_talent(db, talent):
    profile = (
        db.get(TalentProfile, (talent.id, talent.profile_version))
        if talent.profile_version
        else None
    )
    if not profile or talent.status != "active":
        return
    suspend_unrelated_pending(db, talent_id=talent.id)
    for job in db.scalars(
        select(IntakeJob)
        .where(
            IntakeJob.owner_id == talent.owner_id,
            IntakeJob.organization_id == talent.organization_id,
            IntakeJob.status == "active",
            IntakeJob.published_version.is_not(None),
        )
        .order_by(IntakeJob.id)
        .with_for_update()
    ):
        route_to_job(db, talent, profile, job)


def route_job(db, job):
    suspend_unrelated_pending(db, job_id=job.id)
    if not job.routing_directions or job.status != "active" or not job.published_version:
        return
    for talent in db.scalars(
        select(Talent)
        .where(
            Talent.owner_id == job.owner_id,
            Talent.organization_id == job.organization_id,
            Talent.status == "active",
            Talent.profile_version.is_not(None),
        )
        .order_by(Talent.id)
    ):
        route_to_job(db, talent, db.get(TalentProfile, (talent.id, talent.profile_version)), job)


def finish_talent(db, task, talent, data):
    if talent.execution_mode == "live" and "direction_assignments" not in data:
        raise ValueError(
            "Talent extraction must explicitly classify directions or return an empty list"
        )
    profile = prepare_profile(data, talent.material_text, talent.execution_mode)
    version = TalentProfile(
        talent_id=talent.id,
        version=1,
        content=profile.model_dump(mode="json"),
        directions=[item.model_dump() for item in profile.direction_assignments],
        classification_source="mock" if talent.execution_mode == "mock" else "model",
    )
    db.add(version)
    talent.profile_version = 1
    talent.revision += 1
    name = profile.facts.get("name")
    if name and name.status == "stated" and isinstance(name.value, str):
        talent.name = name.value[:200]
    db.flush()
    route_talent(db, talent)
    # This is a talent profile, not a fabricated D03 artifact or hiring result.
    return []


@router.get("/talent-directions", response_model=DirectionCatalog)
def directions(user: User):
    return {
        "version": TAXONOMY_VERSION,
        "items": [{"id": key, "label": value[0]} for key, value in DIRECTIONS.items()],
    }


@router.post("/talent-imports", status_code=202, response_model=TalentReceipt)
async def import_talents(request: Request, db: Db, user: User):
    items, mode, raw = await receive_items(request)

    def action():
        from app.modules.intake.agent_prompts import resource_fingerprint

        settings = request.app.state.settings
        check_mode(settings, mode)
        if len(items) > settings.batch_limit or len({x["client_item_id"] for x in items}) != len(
            items
        ):
            raise DomainError("VALIDATION_ERROR", "批次数量超限或 client_item_id 重复", 422)
        lock_owner(db, user.id)
        receipts = []
        for item in items:
            receipt = {"client_item_id": item["client_item_id"], "name": item["name"]}
            try:
                material = parse_file(
                    "resume.txt" if item["is_text"] else item["name"],
                    item["media_type"],
                    item["data"],
                    settings,
                )
            except DomainError as exc:
                receipts.append({**receipt, "disposition": "invalid", "error_code": exc.code})
                continue
            digest = hashlib.sha256(item["data"]).hexdigest()
            talent = db.scalar(
                select(Talent).where(
                    Talent.owner_id == user.id,
                    Talent.material_hash == digest,
                    Talent.execution_mode == mode,
                )
            )
            if talent:
                if talent.status != "active" or talent.organization_id != user.organization_id:
                    receipts.append(
                        {**receipt, "disposition": "invalid", "error_code": "PRECONDITION_NOT_MET"}
                    )
                    continue
                disposition = "duplicate"
            else:
                talent = Talent(
                    id=new_id(),
                    organization_id=user.organization_id,
                    owner_id=user.id,
                    name=item["name"],
                    filename=item["name"],
                    media_type=item["media_type"],
                    data=item["data"],
                    material_text=material,
                    material_hash=digest,
                    execution_mode=mode,
                    task_id=new_id(),
                )
                db.add(talent)
                db.flush()
                task = enqueue(
                    db,
                    organization_id=user.organization_id,
                    job_id=None,
                    kind="talent_parse",
                    dedup_key=f"talent:{talent.id}:parse:1",
                    payload={
                        "talent_id": talent.id,
                        "execution_mode": mode,
                        "agent_spec_version": 2,
                        "agent_resource_hash": resource_fingerprint(),
                        "input_refs": [{"kind": "material", "id": talent.id, "version": 1}],
                    },
                )
                talent.task_id = task.id
                db.add(
                    Budget(
                        job_id="talent:" + talent.id,
                        call_limit=settings.talent_model_call_limit,
                        token_limit=settings.job_model_token_limit,
                        search_limit=0,
                    )
                )
                disposition = "accepted"
            receipts.append(
                {
                    **receipt,
                    "disposition": disposition,
                    "talent_id": talent.id,
                    "task_id": talent.task_id,
                }
            )
        return {"items": receipts}

    return execute(db, user, request, raw, 202, action)


@router.get("/talents", response_model=TalentPage)
def list_talents(
    db: Db,
    user: User,
    page: PageNumber = 1,
    page_size: PageSize = 20,
    q: Annotated[str | None, Query(max_length=100)] = None,
):
    query = select(Talent).where(
        Talent.owner_id == user.id,
        Talent.organization_id == user.organization_id,
        Talent.status == "active",
    )
    if q:
        query = query.where(Talent.name.icontains(q.strip(), autoescape=True))
    return paginate(
        db,
        query.order_by(Talent.created_at.desc(), Talent.id.desc()),
        page,
        page_size,
        lambda item: talent_view(db, item),
    )


@router.get("/talents/{talent_id}", response_model=TalentDetail)
def read_talent(talent_id: str, db: Db, user: User):
    return talent_view(db, get_talent(db, user, talent_id), detail=True)


@router.get("/talents/{talent_id}/file")
def read_talent_file(talent_id: str, db: Db, user: User):
    talent = get_talent(db, user, talent_id)
    return Response(
        talent.data,
        media_type=talent.media_type,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(talent.filename, safe=""),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.patch("/talents/{talent_id}/directions", response_model=TalentDetail)
def classify_talent(talent_id: str, body: ClassifyTalentInput, db: Db, user: User):
    lock_owner(db, user.id)
    talent = get_talent(db, user, talent_id, lock=True)
    require_revision(talent.revision, body.expected_revision)
    if talent.profile_version is None:
        raise DomainError("PRECONDITION_NOT_MET", "请等待简历提取完成")
    if len({item.direction_id for item in body.directions}) != len(body.directions) or any(
        item.quote not in talent.material_text for item in body.directions
    ):
        raise DomainError("VALIDATION_ERROR", "方向不能重复，分类引用必须来自原始简历", 422)
    old = db.get(TalentProfile, (talent.id, talent.profile_version))
    assignments = [item.model_dump() for item in body.directions]
    profile = TalentProfile(
        talent_id=talent.id,
        version=old.version + 1,
        content={**old.content, "direction_assignments": assignments},
        directions=assignments,
        classification_source="manual",
        classification_note=body.reason,
    )
    db.add(profile)
    talent.profile_version = profile.version
    talent.revision += 1
    db.flush()
    route_talent(db, talent)
    return talent_view(db, talent, detail=True)


@router.post("/talents/{talent_id}/route", response_model=TalentDetail)
def rematch_talent(talent_id: str, body: RematchInput, request: Request, db: Db, user: User):
    get_talent(db, user, talent_id)

    def action():
        lock_owner(db, user.id)
        talent = get_talent(db, user, talent_id, lock=True)
        require_revision(talent.revision, body.expected_revision)
        route_talent(db, talent)
        return talent_view(db, talent, detail=True)

    return execute(db, user, request, body.model_dump(), 200, action)


@router.post(
    "/applications/{application_id}/start-screening",
    status_code=202,
    response_model=dto.TaskAccepted,
)
def start_screening(application_id: str, body: RetryInput, request: Request, db: Db, user: User):
    get_application(db, user, application_id)

    def action():
        lock_owner(db, user.id)
        app = get_application(db, user, application_id, lock=True)
        require_revision(app.revision, body.expected_revision)
        if app.stage != "matched" or not app.talent_id:
            raise DomainError("PRECONDITION_NOT_MET", "只有已分流且尚未启动的候选人可开始深度初筛")
        job = db.get(IntakeJob, app.job_id)
        talent = get_talent(db, user, app.talent_id)
        profile = db.get(TalentProfile, (talent.id, talent.profile_version))
        check_mode(request.app.state.settings, app.execution_mode)
        if (
            job.status != "active"
            or not profile
            or not compatible_directions(profile.directions, job.routing_directions)
            or app.routing["profile_version"] != profile.version
        ):
            raise DomainError("PRECONDITION_NOT_MET", "岗位或分类已变化，请先核对分流结果")
        d03 = latest(db, job.id, "D03", app.id)
        if d03 is None or d03.status != "valid":
            raise DomainError("PRECONDITION_NOT_MET", "简历结构化产物已失效")
        rule = db.get(RulePack, (job.id, app.rule_version))
        if rule is None or (app.execution_mode == "mock" and not rule.is_test_rule):
            raise DomainError("PRECONDITION_NOT_MET", "绑定规则与执行模式不符")
        if rule.is_test_rule:
            check_mode(request.app.state.settings, "mock")
        task = queue_step(db, job, app, "research", input_refs=[artifact_ref(d03)])
        app.stage, app.updated_at = "research", utcnow()
        app.revision += 1
        audit(
            db,
            job,
            user.id,
            "talent.screening_started",
            application_id=app.id,
            refs={"reason": body.reason, "task_id": task.id},
        )
        return accepted(task)

    return execute(db, user, request, body.model_dump(), 202, action)
