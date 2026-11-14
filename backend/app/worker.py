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
    Artifact,
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
    enqueue,
    fence,
    reserve_model,
    resume_known_response,
    settle_model,
)
from app.modules.intake import analysis
from app.modules.intake.evidence_screening import (
    finish_screening,
    model_context,
    uses_evidence_method,
)
from app.modules.intake.form_sources import canonical_resume_facts, resume_objects
from app.modules.intake.schemas import (
    ConfigRef,
    Fact,
    InterviewStandard,
    JobAnalysis,
    ResumeProfile,
    ResumeResearchObject,
    RuleContent,
    ScreeningStandard,
)
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
    from app.modules.intake.agent_prompts import resource_fingerprint

    expected = task.payload.get("agent_resource_hash")
    if expected and expected != resource_fingerprint():
        raise DomainError("AGENT_RESOURCES_CHANGED", "提示词或合同版本已变化，请核对任务输入版本")
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
    elif task.kind in {"job_analysis", "interview_standard", "screening_standard"}:
        if job.draft_revision != task.payload["draft_revision"]:
            raise DomainError("VERSION_CONFLICT", "规则草案已修改，未覆盖人工编辑")
    return job, application


def _finish_model(
    db: Session, task: Task, job: IntakeJob, application: Application | None, data: dict
) -> list[dict]:
    mode = task.payload["execution_mode"]
    if task.kind == "screening":
        return finish_screening(db, task, job, application, data)
    if task.kind in {"interview_standard", "screening_standard"}:
        return _finish_standard(db, task, job, data)
    if task.kind == "job_analysis":
        profile = analysis.validate_quotes(
            JobAnalysis.model_validate(data), analysis.job_material(job)
        )
        if task.payload.get("agent_spec_version") == 2 and profile.job_form is None:
            raise ValueError("A01 output is missing its complete standard form")
        from app.modules.intake.material_job import apply_material_job_labels

        apply_material_job_labels(job, profile)
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
            if profile.job_form:
                from app.modules.intake.form_contracts import SourceFact

                label = {
                    "title": "岗位名称",
                    "company": "客户企业名称",
                    "location": "工作地点",
                    "salary": "转正薪资",
                }[field]
                current = profile.job_form.fields[label]
                if current.status == "stated" and current.value != supplied:
                    profile.job_form.fields[label] = SourceFact(
                        status="conflict", note="岗位关联字段与材料陈述不同，待确认"
                    )
                elif current.status == "unknown":
                    profile.job_form.fields[label] = SourceFact(
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
        if task.payload.get("agent_spec_version") == 2:
            # A01 has no authority to invent interview or screening standards.
            job.draft = RuleContent().model_dump(mode="json")
            job.draft_revision += 1
            job.revision += 1
            _queue_standard(db, task, job, "interview_standard", [artifact_ref(d01)])
            audit(db, job, "worker", "job.a01_completed", refs={"task_id": task.id})
            return [artifact_ref(d01)]
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
    if task.payload.get("agent_spec_version") == 2:
        if profile.resume_form is None:
            raise ValueError("A04 output is missing its nine-module standard form")
        if mode == "live":
            profile.facts.update(
                {
                    key: Fact.model_validate(value)
                    for key, value in canonical_resume_facts(profile.resume_form).items()
                }
            )
            profile.research_objects = [
                ResumeResearchObject.model_validate(
                    {
                        **item,
                        "name": {k: v for k, v in item["name"].items() if k != "evidence_refs"},
                        "period": {k: v for k, v in item["period"].items() if k != "evidence_refs"},
                        "facts": {
                            key: {k: v for k, v in value.items() if k != "evidence_refs"}
                            for key, value in item["facts"].items()
                        },
                    }
                )
                for item in resume_objects(profile.resume_form)
            ]
        if "[[UNREADABLE_" in application.material_text:
            profile.resume_form.parse_status = "partial"
            profile.resume_form.limitations.append(
                "原文件包含尚未识别的页面或嵌入内容，需补充文字材料"
            )
    artifact = save_profile(
        db,
        job,
        {
            **profile.model_dump(mode="json"),
            "unknown_fields": sorted(
                set(profile.unknown_fields)
                | {key for key, fact in profile.facts.items() if fact.status != "stated"}
            ),
        },
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


def _queue_standard(db, parent, job, kind, inputs):
    from app.modules.intake.agent_prompts import resource_fingerprint

    child = enqueue(
        db,
        organization_id=job.organization_id,
        job_id=job.id,
        kind=kind,
        dedup_key=f"job:{job.id}:{job.draft_revision}:{kind}",
        payload={
            "draft_revision": job.draft_revision,
            "execution_mode": parent.payload["execution_mode"],
            "agent_spec_version": 2,
            "agent_resource_hash": resource_fingerprint(),
            "parent_task_id": parent.id,
            "input_refs": inputs,
        },
    )
    parent.payload = {**parent.payload, "continuation_task_id": child.id}


def _finish_standard(db, task, job, data):
    rules = RuleContent.model_validate(job.draft)
    if task.kind == "interview_standard":
        standard = InterviewStandard.model_validate(data)
        if any(
            quote not in analysis.job_material(job)
            for dimension in standard.dimensions
            for quote in dimension.source_quotes
        ):
            raise ValueError("A02 standard lacks original job support")
        rules.interview_dimensions = standard.dimensions
        rules.interview_text = "按经确认的岗位专属能力与五档锚点评估；未知保持未评估"
        artifact = save_artifact(
            db,
            job,
            "D02",
            {
                "rules": rules.model_dump(mode="json"),
                "gaps": standard.gaps,
                "confirmation_status": "draft" if standard.dimensions else "needs_information",
            },
            source=task.payload["execution_mode"],
            inputs=task.payload["input_refs"],
        )
        job.draft = rules.model_dump(mode="json")
        job.draft_revision += 1
        _queue_standard(
            db,
            task,
            job,
            "screening_standard",
            [*task.payload["input_refs"], artifact_ref(artifact)],
        )
        refs = [artifact_ref(artifact)]
    else:
        standard = ScreeningStandard.model_validate(data)
        if standard.rubric and any(
            quote not in analysis.job_material(job)
            for dimension in standard.rubric.dimensions
            for quote in dimension.source_quotes
        ):
            raise ValueError("A05 job rule lacks original job support")
        rules.screening_rubric = standard.rubric
        rules.screening_text = "七维证据初筛；同岗位固定版本；未知不扣分；三分流须说明证据"
        rules.method_config_ref = ConfigRef(config_id="a05-evidence", version=1)
        rules.research_config_ref = ConfigRef(config_id="pi-research", version=1)
        rules.phone_config_ref = ConfigRef(config_id="disabled", version=1)
        # Recommendation remains a separate, explicitly reviewed business configuration.
        job.draft = RuleContent.model_validate(rules.model_dump(mode="json")).model_dump(
            mode="json"
        )
        job.draft_revision += 1
        refs = task.payload["input_refs"]
        task.payload = {**task.payload, "gaps": standard.gaps}
    job.revision += 1
    job.updated_at = utcnow()
    audit(db, job, "worker", task.kind + ".completed", refs={"task_id": task.id})
    return refs


def _model_material(db, task, job, application):
    if task.kind == "screening":
        return model_context(db, job, application)
    if task.kind in {"interview_standard", "screening_standard"}:
        import json

        artifacts = [
            db.get(Artifact, (ref["artifact_id"], ref["version"]))
            for ref in task.payload["input_refs"]
        ]
        if any(a is None or a.status != "valid" or a.job_id != job.id for a in artifacts):
            raise DomainError("PRECONDITION_NOT_MET", "岗位建议标准输入已失效")
        return json.dumps(
            {
                "original_job_material": analysis.job_material(job),
                "job_title": job.title,
                "artifacts": {a.type: a.content for a in artifacts},
            },
            ensure_ascii=False,
        )
    return application.material_text if application else analysis.job_material(job)


def _complete_model_task(db, task):
    if task.payload.get("continuation_task_id"):
        task.status, task.finished_at = "waiting_conditions", None
    else:
        task.status, task.finished_at = "completed", utcnow()
        child = task
        while child.payload.get("parent_task_id"):
            parent = db.get(Task, child.payload["parent_task_id"])
            if not parent or parent.payload.get("continuation_task_id") != child.id:
                raise DomainError("PRECONDITION_NOT_MET", "岗位任务链关联已失效")
            if parent.status != "waiting_conditions":
                raise DomainError("PRECONDITION_NOT_MET", "岗位前置任务状态已变化")
            refs = parent.result_refs + child.result_refs
            parent.result_refs = list(
                {(ref["artifact_id"], ref["version"]): ref for ref in refs}.values()
            )
            parent.status, parent.finished_at, parent.error_code = "completed", utcnow(), None
            parent.revision += 1
            child = parent
    task.revision += 1


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
    if task.status == "failed" and task.payload.get("parent_task_id"):
        child = task
        while child.payload.get("parent_task_id"):
            parent = db.get(Task, child.payload["parent_task_id"])
            if not parent or parent.payload.get("continuation_task_id") != child.id:
                break
            if parent.status == "waiting_conditions":
                parent.status, parent.error_code = "failed", task.error_code
                parent.finished_at = utcnow()
                parent.revision += 1
            child = parent
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
    kinds = {
        "job_analysis",
        "interview_standard",
        "screening_standard",
        "resume_parse",
        "research",
        *INTERNAL_HANDLERS,
    }
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
            evidence_screen = (
                task.kind == "screening"
                and application is not None
                and uses_evidence_method(db.get(RulePack, (job.id, application.rule_version)))
            )
            if (
                task.kind
                not in {"job_analysis", "interview_standard", "screening_standard", "resume_parse"}
                and not evidence_screen
            ):
                task.result_refs = INTERNAL_HANDLERS[task.kind](db, task, job, application)
                task.status, task.finished_at = "completed", utcnow()
                task.revision += 1
                refresh_batches(db, task.id)
                return True
            material = _model_material(db, task, job, application)
            kind = task.kind
            if mode == "mock":
                data = analysis.mock_analysis(kind, material)
                task.result_refs = _finish_model(db, task, job, application, data)
                _complete_model_task(db, task)
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
                _complete_model_task(db, task)
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
            task.payload = {**task.payload, "model_reported_tokens": tokens if tokens > 0 else None}
            resume_known_response(task, settings)
        submitted = False
        with Session(engine) as db, db.begin():
            task = db.get(Task, task_id)
            job, application = _context(db, task)
            task = fence(db, task_id, token)
            task.result_refs = _finish_model(db, task, job, application, data)
            _complete_model_task(db, task)
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
