"""Bounded research collection. Search results never establish personal contribution."""

import hashlib
import json
import re

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.core.artifacts import artifact_ref, evidence_ref, latest, save_artifact
from app.core.config import Settings
from app.core.errors import DomainError
from app.core.models import Artifact, Budget, Evidence, RulePack, SearchUsage, Task, utcnow
from app.core.tasks import fence, resume_known_response
from app.integrations.search import (
    SearchResult,
    allowed_domains,
    get_search_adapter,
    public_source_url,
)
from app.modules.intake.content import usage
from app.modules.intake.service import check_mode, queue_step


def research_plan(d03: Artifact, settings: Settings) -> list[dict]:
    facts = d03.content["facts"]
    plan = []
    for subject_type, keys in (("company", ("employer", "company")), ("project", ("project",))):
        fact = next(
            (facts[key] for key in keys if facts.get(key, {}).get("status") == "stated"), {}
        )
        name = fact.get("value")
        if not isinstance(name, str):
            continue
        name = " ".join(name.split())
        # Only bounded organization/project labels leave the system; no resume/contact/person query.
        if not 2 <= len(name) <= 200 or "@" in name or re.search(r"\d{7,}", name):
            continue
        period = facts.get(
            "employment_period" if subject_type == "company" else "project_period", {}
        )
        years = str(period.get("value", "")) if period.get("status") == "stated" else ""
        if not re.fullmatch(r"(?:19|20)\d{2}(?:\s*[-—至]\s*(?:19|20)\d{2})?", years):
            years = ""
        plan.append(
            {
                "subject_type": subject_type,
                "name": name,
                "period": years or None,
                "evidence_refs": fact.get("evidence_refs", []),
                "query": f'"{name}" {subject_type} official background {years}'.strip(),
            }
        )
    return plan[: settings.research_query_limit]


def reserve_search(
    db: Session, task: Task, sequence: int, query: str, provider: str
) -> SearchUsage:
    existing = db.get(SearchUsage, (task.id, sequence))
    if existing:
        if existing.query_hash != hashlib.sha256(query.encode()).hexdigest():
            raise DomainError("PRECONDITION_NOT_MET", "检索输入快照不一致")
        if existing.status != "settled":
            raise DomainError("EXTERNAL_RESULT_UNKNOWN", "已有搜索请求待核对，不能重复提交")
        return existing
    updated = db.execute(
        update(Budget)
        .where(
            Budget.job_id == task.job_id,
            Budget.searches_reserved + Budget.searches_used < Budget.search_limit,
        )
        .values(searches_reserved=Budget.searches_reserved + 1)
    )
    if updated.rowcount != 1:
        raise DomainError("BUDGET_EXCEEDED", "搜索次数预算不足", 429)
    record = SearchUsage(
        task_id=task.id,
        sequence=sequence,
        job_id=task.job_id,
        request_id=f"{task.id}:search:{sequence}",
        provider=provider,
        query_hash=hashlib.sha256(query.encode()).hexdigest(),
        status="submitted",
    )
    db.add(record)
    task.external_state = "submitted"
    db.flush()
    return record


def settle_search(
    db: Session, task_id: str, sequence: int, response: SearchResult, settings: Settings
):
    record = db.scalar(
        select(SearchUsage)
        .where(SearchUsage.task_id == task_id, SearchUsage.sequence == sequence)
        .with_for_update()
    )
    if record is None or record.status not in {"submitted", "unknown"}:
        raise DomainError("INVALID_STATE_TRANSITION", "搜索请求记录状态不符")
    record.result_payload = response.model_dump(mode="json")
    record.status, record.finished_at = "settled", utcnow()
    db.execute(
        update(Budget)
        .where(Budget.job_id == record.job_id)
        .values(
            searches_reserved=Budget.searches_reserved - 1, searches_used=Budget.searches_used + 1
        )
    )
    task = db.get(Task, task_id)
    resume_known_response(task, settings)


def collect_report(db, job, application, d03, *, plan, responses, source, domains, reason):
    refs, findings, sources, rejected, assertions = [], [], [], 0, {}
    collected_types = set()
    for subject, response in zip(plan, responses, strict=False):
        for hit in response.results:
            url = public_source_url(hit.url, domains)
            if url is None:
                rejected += 1
                continue
            collected_types.add(subject["subject_type"])
            evidence = Evidence(
                organization_id=job.organization_id,
                job_id=job.id,
                application_id=application.id,
                source_type="public_web",
                category="U",
                quote=hit.snippet,
                public_url=url,
                source_date=hit.published_at,
                location={
                    "section": "search_snippet",
                    "subject": subject["name"],
                    "title": hit.title,
                },
                source_mode=source,
            )
            db.add(evidence)
            db.flush()
            ref = evidence_ref(evidence)
            refs.append(ref)
            sources.append(
                {
                    "url": url,
                    "subject_type": subject["subject_type"],
                    "declared_subject": subject["name"],
                    "title": hit.title,
                    "evidence_ref": ref,
                    "published_at": hit.published_at.isoformat() if hit.published_at else None,
                    "subject_identity": "unverified",
                    "historical_applicability": "unknown",
                }
            )
            findings.append(
                {
                    "text": f"待核实搜索摘要（{subject['name']}）：{hit.snippet}",
                    "evidence_refs": [ref],
                    "category": "U",
                }
            )
            for assertion in hit.assertions:
                if assertion.quote not in hit.snippet or assertion.value not in assertion.quote:
                    continue
                key = (subject["subject_type"], subject["name"], assertion.field)
                assertions.setdefault(key, []).append(
                    {"value": assertion.value, "quote": assertion.quote, "evidence_ref": ref}
                )
    conflicts = [
        f"{key[1]} 的 {key[2]} 来源陈述不同；尚未确认是否同一主体，不合并结论"
        for key, values in assertions.items()
        if len({item["value"] for item in values}) > 1
    ]
    gaps = ["搜索摘要不是已核实事实；主体对应关系、任职历史适用性和个人贡献均待核实"]
    if not refs:
        gaps.append("没有可引用的允许来源")
    if any(not subject["period"] for subject in plan):
        gaps.append("材料未提供明确历史期间")
    data = {
        "status": "partial" if responses else "not_executed",
        "fields": {
            "subject_identity": "unknown",
            "company_context": "unverified" if "company" in collected_types else "unknown",
            "project_context": "unverified" if "project" in collected_types else "unknown",
            "historical_time": "unknown",
            "personal_contribution": "unknown",
        },
        "subjects": [f"{subject['subject_type']}:{subject['name']}" for subject in plan],
        "declared_subjects": [
            {
                **{k: v for k, v in subject.items() if k != "query"},
                "execution_state": "collected" if index < len(responses) else "not_executed",
            }
            for index, subject in enumerate(plan)
        ],
        "findings": findings,
        "sources": sources,
        "conflicts": conflicts,
        "source_assertions": [
            {"subject": key[1], "field": key[2], "statements": values}
            for key, values in assertions.items()
        ],
        "gaps": gaps,
        "stop_reason": {
            "code": reason,
            "message": "有界研究已停止，缺口保留待复核",
            "missing_fields": ["verified_identity", "historical_context", "personal_contribution"],
        },
        "usage": usage(search_count=len(responses)),
        "rejected_source_count": rejected,
    }
    artifact = save_artifact(
        db,
        job,
        "D04",
        data,
        application=application,
        source=source if responses else "manual",
        inherited=[d03.source_mode, *d03.inherited_source_modes],
        inputs=[artifact_ref(d03)],
        evidence=refs,
    )
    application.stage = "screening"
    application.updated_at = utcnow()
    application.revision += 1
    queue_step(
        db, job, application, "screening", input_refs=[artifact_ref(d03), artifact_ref(artifact)]
    )
    return [artifact_ref(artifact)]


def run_research_task(
    settings: Settings, engine: Engine, task_id: str, token: str, context, refresh
):
    with Session(engine) as db, db.begin():
        task = db.get(Task, task_id)
        job, application = context(db, task)
        task = fence(db, task_id, token)
        check_mode(settings, task.payload["execution_mode"])
        d03 = latest(db, job.id, "D03", application.id)
        if d03 is None:
            raise DomainError("PRECONDITION_NOT_MET", "缺少有效 D03")
        rule = db.get(RulePack, (job.id, application.rule_version))
        selected = rule.content["research_config_ref"]["config_id"]
        if selected == "pi-research":
            # End this transaction before Pi makes any external requests.
            use_pi = True
        else:
            use_pi = False
    if use_pi:
        from app.modules.intake.a03_runtime import run_pi_research

        return run_pi_research(settings, engine, task_id, token, context, refresh)
    with Session(engine) as db, db.begin():
        task = db.get(Task, task_id)
        job, application = context(db, task)
        task = fence(db, task_id, token)
        d03 = latest(db, job.id, "D03", application.id)
        rule = db.get(RulePack, (job.id, application.rule_version))
        selected = rule.content["research_config_ref"]["config_id"]
        adapter, domains, reason = None, [], "RESEARCH_DISABLED_BY_PUBLISHED_RULE"
        if selected == "bounded-research":
            adapter = get_search_adapter(settings)
            domains = allowed_domains(settings)
            reason = (
                "SEARCH_PROVIDER_UNAVAILABLE"
                if adapter is None
                else "RESEARCH_SOURCES_NOT_CONFIGURED"
            )
        mock_input = "mock" in {
            task.payload["execution_mode"],
            d03.source_mode,
            *d03.inherited_source_modes,
            *d03.source_modes.values(),
        }
        if adapter and mock_input and adapter.source_mode != "mock":
            adapter, reason = None, "MOCK_INPUT_NOT_SENT_TO_LIVE_SEARCH"
        plan = task.payload.get("research_plan")
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "provider": settings.search_provider,
                    "endpoint_hash": hashlib.sha256(
                        (settings.search_endpoint or "").encode()
                    ).hexdigest(),
                    "domains": domains,
                    "source_mode": adapter.source_mode if adapter else None,
                    "query_limit": settings.research_query_limit,
                    "result_limit": settings.search_result_limit,
                    "timeout_seconds": settings.search_timeout_seconds,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        if plan is None:
            plan = research_plan(d03, settings)
            task.payload = {
                **task.payload,
                "research_plan": plan,
                "search_provider": settings.search_provider,
                "search_allowed_domains": domains,
                "search_configuration_hash": fingerprint,
            }
        elif task.payload.get("search_configuration_hash") != fingerprint:
            raise DomainError("PRECONDITION_NOT_MET", "搜索执行配置已改变，请核对原任务")
        if not adapter or not plan:
            if adapter and not plan:
                reason = "NO_UNAMBIGUOUS_SUBJECT_OR_QUERY_LIMIT"
            task.result_refs = collect_report(
                db,
                job,
                application,
                d03,
                plan=plan,
                responses=[],
                source="manual",
                domains=domains,
                reason=reason,
            )
            task.status, task.finished_at = "completed", utcnow()
            task.revision += 1
            refresh(db, task.id)
            return
        if (
            task.payload["search_provider"] != settings.search_provider
            or task.payload["search_allowed_domains"] != domains
        ):
            raise DomainError("PRECONDITION_NOT_MET", "搜索执行配置已改变，请核对原任务")
        source = adapter.source_mode
    responses = []
    reason = "FIXED_PLAN_COMPLETED"
    for sequence, subject in enumerate(plan, start=1):
        try:
            with Session(engine) as db, db.begin():
                task = db.get(Task, task_id)
                context(db, task)
                task = fence(db, task_id, token)
                record = reserve_search(
                    db, task, sequence, subject["query"], settings.search_provider
                )
                cached, request_id = record.result_payload, record.request_id
        except DomainError as exc:
            if exc.code != "BUDGET_EXCEEDED":
                raise
            reason = "BUDGET_EXCEEDED"
            break
        if cached is None:
            response = adapter.search(subject["query"], request_id=request_id)
            response = SearchResult.model_validate(response)
            response = SearchResult(results=response.results[: settings.search_result_limit])
            with Session(engine) as db, db.begin():
                settle_search(db, task_id, sequence, response, settings)
        else:
            response = SearchResult.model_validate(cached)
        responses.append(response)
    with Session(engine) as db, db.begin():
        task = db.get(Task, task_id)
        job, application = context(db, task)
        task = fence(db, task_id, token)
        d03 = latest(db, job.id, "D03", application.id)
        task.result_refs = collect_report(
            db,
            job,
            application,
            d03,
            plan=plan,
            responses=responses,
            source=source,
            domains=domains,
            reason=reason,
        )
        task.status, task.finished_at = "completed", utcnow()
        task.revision += 1
        refresh(db, task.id)
