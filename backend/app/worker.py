"""Durable intake worker. Run separately from the HTTP process."""

import argparse
import time
from collections.abc import Callable

import httpx
from pydantic import ValidationError
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.artifacts import artifact_ref, latest, require_application_file, save_artifact
from app.core.config import Settings, get_settings
from app.core.database import get_engine
from app.core.errors import DomainError
from app.core.models import (
    Application,
    BatchItem,
    Identity,
    IntakeJob,
    ModelUsage,
    ResearchAction,
    ResumeBatch,
    RulePack,
    SearchUsage,
    Task,
    utcnow,
)
from app.core.tasks import (
    INTERNAL_KINDS,
    claim,
    fence,
    reserve_model,
    resume_known_response,
    settle_model,
)
from app.modules.intake import analysis
from app.modules.intake.schemas import Fact, JobAnalysis, ResumeProfile, RuleContent
from app.modules.intake.service import (
    audit,
    check_mode,
    publish_handoff,
    queue_step,
    save_profile,
    screening_decision,
)

Handler = Callable[[Session, Task, IntakeJob, Application | None], list[dict]]
INTERNAL_HANDLERS: dict[str, Handler] = {}


def register_internal_handler(kind: str, handler: Handler):
    """Extension point for B's pure internal computation; never register dial/send here."""
    if kind not in {
        "interview_outline",
        "interview_extract",
        "evaluation",
        "recommendation",
        "recompute",
    }:
        raise ValueError("Only supported internal computation kinds may be registered")
    if kind in INTERNAL_HANDLERS:
        raise ValueError("Task kind already registered or reserved")
    INTERNAL_HANDLERS[kind] = handler
    INTERNAL_KINDS.add(kind)


def _context(db: Session, task: Task) -> tuple[IntakeJob, Application | None]:
    job = db.scalar(select(IntakeJob).where(IntakeJob.id == task.job_id).with_for_update())
    if job is None or job.organization_id != task.organization_id:
        raise DomainError("PRECONDITION_NOT_MET", "任务对象已不可访问")
    owner = db.get(Identity, job.owner_id)
    if owner is None or not owner.enabled or owner.organization_id != task.organization_id:
        raise DomainError("PERMISSION_DENIED", "任务所属账号已不可用", 403)
    if job.status != "active":
        raise DomainError("PRECONDITION_NOT_MET", "岗位已暂停或归档")
    application = db.get(Application, task.application_id) if task.application_id else None
    if task.application_id:
        if (
            application is None
            or application.job_id != job.id
            or application.organization_id != task.organization_id
            or application.status != "active"
            or application.generation != task.payload["generation"]
            or application.rule_version != task.payload["rule_version"]
        ):
            raise DomainError("PRECONDITION_NOT_MET", "任务输入已失效")
        require_application_file(db, application)
    elif task.kind == "job_analysis":
        if job.draft_revision != task.payload["draft_revision"]:
            raise DomainError("VERSION_CONFLICT", "规则草案已修改，未覆盖人工编辑")
    return job, application


def _finish_model(
    db: Session, task: Task, job: IntakeJob, application: Application | None, data: dict
) -> list[dict]:
    mode = task.payload["execution_mode"]
    if task.kind == "job_analysis":
        profile = analysis.validate_quotes(JobAnalysis.model_validate(data), job.material_text)
        for field in ("title", "company", "location", "salary"):
            supplied = job.material_fields.get(field)
            if supplied is None:
                continue
            extracted = profile.facts.get(field)
            if extracted and extracted.status == "stated" and str(extracted.value) != supplied:
                profile.facts[field] = Fact(value=None, status="conflict")
            else:
                profile.facts[field] = Fact(
                    value=supplied, status="stated", quote=f"{field}: {supplied}"
                )
        profile.unknown_fields = sorted(
            key for key, fact in profile.facts.items() if fact.status != "stated"
        )
        d01 = save_profile(
            db,
            job,
            profile.model_dump(mode="json", exclude={"rules"}),
            "D01",
            source=mode,
            inherited=["manual"],
            inputs=task.payload.get("input_refs", []),
        )
        d02 = save_artifact(
            db,
            job,
            "D02",
            {"rules": profile.rules.model_dump(mode="json")},
            source=mode,
            inherited=["manual"],
            inputs=[artifact_ref(d01)],
        )
        job.draft = profile.rules.model_dump(mode="json")
        job.draft_revision += 1
        job.revision += 1
        job.updated_at = utcnow()
        audit(db, job, "worker", "job.analyzed", refs={"task_id": task.id})
        return [artifact_ref(d01), artifact_ref(d02)]
    if application is None:
        raise DomainError("PRECONDITION_NOT_MET", "简历任务缺少关联")
    profile = analysis.validate_quotes(
        ResumeProfile.model_validate(data), application.material_text
    )
    artifact = save_profile(
        db,
        job,
        profile.model_dump(mode="json"),
        "D03",
        source=mode,
        application=application,
        inherited=["manual"],
        inputs=[{"kind": "material", "id": application.file_id, "version": 1}],
    )
    application.stage = "research"
    name = profile.facts.get("name")
    if name and name.status == "stated" and isinstance(name.value, str) and len(name.value) <= 100:
        application.name = name.value
    application.revision += 1
    application.updated_at = utcnow()
    queue_step(db, job, application, "research", input_refs=[artifact_ref(artifact)])
    return [artifact_ref(artifact)]


def screen(db: Session, task: Task, job: IntakeJob, application: Application) -> list[dict]:
    rule = db.get(RulePack, (job.id, application.rule_version))
    d03 = latest(db, job.id, "D03", application.id)
    d04 = latest(db, job.id, "D04", application.id)
    if rule is None or d03 is None or d04 is None:
        raise DomainError("PRECONDITION_NOT_MET", "缺少规则或有效上游产物")
    content = RuleContent.model_validate(rule.content)
    result, checks, gaps = screening_decision(d03.content, content)
    inherited = sorted(
        {
            mode
            for artifact in (d03, d04)
            for mode in [artifact.source_mode, *artifact.inherited_source_modes]
        }
    )
    d05 = save_artifact(
        db,
        job,
        "D05",
        {
            "facts": d03.content["facts"],
            "unknown_fields": d03.content["unknown_fields"],
            "contribution_warning": "简历为候选人陈述，公开公司成果不代表个人贡献",
            "research_gaps": d04.content["gaps"],
        },
        application=application,
        source="manual",
        inherited=inherited,
        inputs=[artifact_ref(d03), artifact_ref(d04)],
        evidence=[*d03.evidence_refs, *d04.evidence_refs],
    )
    d06 = save_artifact(
        db,
        job,
        "D06",
        {
            "result": result,
            "checks": checks,
            "gaps": gaps,
            "decision_method": "published_predicates_v1",
        },
        application=application,
        source="manual",
        inherited=inherited,
        inputs=[artifact_ref(d05), rule.d01_ref, rule.d02_ref],
        evidence=[*d03.evidence_refs, *d04.evidence_refs],
    )
    application.screening_result = result
    application.gaps = gaps
    application.stage = "outreach" if result == "passed" else "screening"
    application.revision += 1
    application.updated_at = utcnow()
    publish_handoff(db, job, application, rule, d06)
    audit(
        db,
        job,
        "worker",
        "screening.completed",
        application_id=application.id,
        refs={"result": result, "d06_ref": artifact_ref(d06)},
    )
    return [artifact_ref(d05), artifact_ref(d06)]


INTERNAL_HANDLERS.update({"screening": screen})


def refresh_batches(db: Session, task_id: str):
    from app.modules.intake.views import batch_view

    task = db.get(Task, task_id)
    if task is None:
        return
    if task.kind == "batch":
        batch_ids = [task.payload["batch_id"]]
    elif task.application_id:
        batch_ids = list(
            db.scalars(
                select(BatchItem.batch_id).where(BatchItem.application_id == task.application_id)
            )
        )
    else:
        return
    db.flush()
    for batch_id in set(batch_ids):
        batch = db.get(ResumeBatch, batch_id)
        parent = db.get(Task, batch.task_id)
        status = batch_view(db, batch)["status"]
        parent.status = {"processing": "running", "partial_failed": "failed"}.get(status, status)
        parent.revision += 1
        parent.error_code = "BATCH_ITEM_FAILED" if parent.status == "failed" else None
        if parent.status in {"completed", "failed", "cancelled"}:
            parent.finished_at = utcnow()


def run_once(settings: Settings, engine: Engine | None = None) -> bool:
    if engine is None:
        if settings.database_url is None:
            raise DomainError("DEPENDENCY_NOT_READY", "尚未配置数据库", 503)
        engine = get_engine(settings.database_url.get_secret_value())
    kinds = {"job_analysis", "resume_parse", "research", *INTERNAL_HANDLERS}
    with Session(engine) as db, db.begin():
        lease = claim(
            db, settings, kinds, on_recovery=lambda session, task: refresh_batches(session, task.id)
        )
    if lease is None:
        return False
    task_id, token = lease
    submitted = False
    try:
        with Session(engine) as db:
            kind = db.get(Task, task_id).kind
        if kind == "research":
            from app.modules.intake.research import run_research_task

            run_research_task(settings, engine, task_id, token, _context, refresh_batches)
            return True
        with Session(engine) as db, db.begin():
            task = db.get(Task, task_id)
            job, application = _context(db, task)
            task = fence(db, task_id, token)
            mode = task.payload.get("execution_mode", "live")
            check_mode(settings, mode)
            if task.kind not in {"job_analysis", "resume_parse"}:
                task.result_refs = INTERNAL_HANDLERS[task.kind](db, task, job, application)
                task.status, task.finished_at = "completed", utcnow()
                task.revision += 1
                refresh_batches(db, task.id)
                return True
            material = application.material_text if application else job.material_text
            kind = task.kind
            if mode == "mock":
                data = analysis.mock_analysis(kind, material)
                task.result_refs = _finish_model(db, task, job, application, data)
                task.status, task.finished_at = "completed", utcnow()
                task.revision += 1
                refresh_batches(db, task.id)
                return True
            previous_usage = db.get(ModelUsage, task.id)
            if (
                task.external_state == "settled"
                and previous_usage
                and previous_usage.result_payload is not None
            ):
                task.result_refs = _finish_model(
                    db, task, job, application, previous_usage.result_payload
                )
                task.status, task.finished_at = "completed", utcnow()
                task.revision += 1
                refresh_batches(db, task.id)
                return True
            analysis.model_ready(settings)
            request_bytes = len(str(analysis.model_messages(kind, material)).encode("utf-8"))
            reserve_model(db, task, request_bytes + settings.model_max_output_tokens + 1024)
            task.external_state = "submitted"
        submitted = True
        data, tokens = analysis.invoke_model(settings, kind, material, f"{task_id}:{token}")
        # Record known usage even if an intervening correction made the result stale.
        with Session(engine) as db, db.begin():
            task = db.get(Task, task_id)
            settle_model(db, task, tokens)
            db.get(ModelUsage, task.id).result_payload = data
            resume_known_response(task, settings)
        submitted = False
        with Session(engine) as db, db.begin():
            task = db.get(Task, task_id)
            job, application = _context(db, task)
            task = fence(db, task_id, token)
            task.result_refs = _finish_model(db, task, job, application, data)
            task.status, task.finished_at = "completed", utcnow()
            task.revision += 1
            refresh_batches(db, task.id)
    except Exception as exc:
        # Never persist third-party exception text. Unknown external outcomes retain budget.
        if isinstance(exc, DomainError):
            code = exc.code
        elif isinstance(exc, (ValidationError, ValueError, KeyError, TypeError)):
            code = "INVALID_SEARCH_OUTPUT" if kind == "research" else "INVALID_MODEL_OUTPUT"
        elif isinstance(exc, httpx.HTTPError):
            code = "UPSTREAM_UNAVAILABLE"
        else:
            code = "INTERNAL_ERROR"
        with Session(engine) as db, db.begin():
            task = db.get(Task, task_id)
            if task and task.lease_token == token and task.status == "running":
                unknown = submitted or task.external_state in {"submitted", "unknown"}
                task.status = "reconciling" if unknown else "failed"
                task.external_state = "unknown" if unknown else task.external_state
                task.error_code = "EXTERNAL_RESULT_UNKNOWN" if unknown else code
                if unknown:
                    for action in db.scalars(
                        select(ResearchAction).where(
                            ResearchAction.task_id == task.id,
                            ResearchAction.status == "submitted",
                        )
                    ):
                        action.status = "unknown"
                    for request in db.scalars(
                        select(SearchUsage).where(
                            SearchUsage.task_id == task.id, SearchUsage.status == "submitted"
                        )
                    ):
                        request.status = "unknown"
                task.finished_at = utcnow()
                task.revision += 1
                refresh_batches(db, task_id)
    return True


def main():
    parser = argparse.ArgumentParser(description="Run durable intake tasks; no phone or delivery.")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--drain", action="store_true", help="Process queued work, then exit")
    args = parser.parse_args()
    settings = get_settings()
    while True:
        try:
            worked = run_once(settings)
        except Exception:
            raise SystemExit(
                "Worker unavailable; check database configuration and migrations"
            ) from None
        if args.once or (args.drain and not worked):
            break
        if not worked:
            time.sleep(3)


if __name__ == "__main__":
    main()
