from datetime import timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import DomainError
from app.core.models import Budget, ModelUsage, ResearchAction, SearchUsage, Task, new_id, utcnow

INTERNAL_KINDS = {"job_analysis", "resume_parse", "research", "screening"}


def enqueue(
    db: Session,
    *,
    organization_id: str,
    job_id: str,
    kind: str,
    dedup_key: str,
    payload: dict,
    application_id: str | None = None,
) -> Task:
    task = db.scalar(select(Task).where(Task.dedup_key == dedup_key))
    if task is None:
        task = Task(
            organization_id=organization_id,
            job_id=job_id,
            kind=kind,
            application_id=application_id,
            dedup_key=dedup_key,
            payload=payload,
        )
        db.add(task)
        db.flush()
    return task


def accepted(task: Task) -> dict:
    return {
        "task_id": task.id,
        "resource_type": "batch"
        if task.kind == "batch"
        else "application"
        if task.application_id
        else "job",
        "resource_id": task.payload["batch_id"]
        if task.kind == "batch"
        else task.application_id or task.job_id,
        "poll_after_ms": 3000,
    }


def retryable(task: Task, settings: Settings) -> bool:
    return (
        task.kind in INTERNAL_KINDS
        and task.status == "failed"
        and task.external_state in {None, "settled"}
        and task.attempt_count < settings.task_attempt_limit
    )


def resume_known_response(task: Task, settings: Settings):
    """A late authoritative response permits internal recovery, never resubmission."""
    task.external_state = "settled"
    if task.status == "reconciling":
        task.lease_token, task.lease_until = None, None
        task.revision += 1
        if task.attempt_count < settings.task_attempt_limit:
            task.status, task.error_code, task.finished_at = "queued", None, None
        else:
            task.status, task.error_code = "failed", "ATTEMPT_LIMIT_REACHED"


def task_view(task: Task, settings: Settings, db: Session) -> dict:
    from app.core.models import aware
    from app.modules.intake.content import usage

    can_retry = retryable(task, settings)
    model_usage = db.get(ModelUsage, task.id)
    searches = list(db.scalars(select(SearchUsage).where(SearchUsage.task_id == task.id)))
    agent_actions = list(
        db.scalars(select(ResearchAction).where(ResearchAction.task_id == task.id))
    )
    model_actions = [item for item in agent_actions if item.kind == "model"]
    reported_tokens = [
        (item.result_payload or {}).get("usage", {}).get("totalTokens") for item in model_actions
    ]
    agent_tokens = (
        sum(reported_tokens)
        if model_actions
        and all(item.status == "settled" for item in model_actions)
        and all(isinstance(value, int) and value > 0 for value in reported_tokens)
        else None
    )
    search_count = (
        None
        if any(item.status != "settled" for item in searches)
        else len(searches)
        if searches or (task.kind == "research" and task.status == "completed")
        else None
    )
    if agent_actions:
        agent_searches = [item for item in agent_actions if item.kind == "search"]
        search_count = (
            len(agent_searches)
            if all(item.status == "settled" for item in agent_searches)
            else None
        )
    budget = db.get(Budget, task.job_id)
    refs = [
        (
            {"kind": "artifact", "id": ref["artifact_id"], "version": ref["version"]}
            if "artifact_id" in ref
            else ref
        )
        for ref in task.payload.get("input_refs", [])
    ]
    return {
        "id": task.id,
        "kind": task.kind,
        "status": task.status,
        "revision": task.revision,
        "resource_type": "batch"
        if task.kind == "batch"
        else "application"
        if task.application_id
        else "job",
        "resource_id": task.payload["batch_id"]
        if task.kind == "batch"
        else task.application_id or task.job_id,
        "input_refs": refs,
        "result_refs": task.result_refs,
        "reason": {"code": task.error_code, "message": "请核对任务状态与依赖", "missing_fields": []}
        if task.error_code
        else None,
        "error": {
            "code": task.error_code,
            "message": "任务未完成",
            "request_id": task.id,
            "details": None,
        }
        if task.error_code
        else None,
        "attempt_count": task.attempt_count,
        "retryable": can_retry,
        "allowed_actions": ["retry"] if can_retry else [],
        "poll_after_ms": None if task.status in {"completed", "failed", "cancelled"} else 3000,
        "usage": usage(
            tokens=agent_tokens
            if agent_actions
            else model_usage.actual_tokens
            if model_usage
            else None,
            search_count=search_count,
        ),
        "budget": {
            "limit": None,
            "reserved": None,
            "settled": None,
            "estimated": None,
            "remaining": None,
            "currency": "CNY",
            "reconciliation_status": "unknown"
            if task.external_state == "unknown"
            else "not_required",
            "model_calls": {
                "limit": budget.call_limit,
                "reserved": budget.reserved,
                "used": budget.used,
            }
            if budget
            else None,
            "model_tokens": {
                "limit": budget.token_limit,
                "reserved": budget.tokens_reserved,
                "used": budget.tokens_used,
            }
            if budget
            else None,
            "search_calls": {
                "limit": budget.search_limit,
                "reserved": budget.searches_reserved,
                "used": budget.searches_used,
            }
            if budget
            else None,
        },
        "created_at": aware(task.created_at),
        "started_at": aware(task.started_at) if task.started_at else None,
        "finished_at": aware(task.finished_at) if task.finished_at else None,
    }


def claim(
    db: Session, settings: Settings, kinds: set[str], *, on_recovery=None
) -> tuple[str, str] | None:
    now = utcnow()
    expired = list(
        db.scalars(
            select(Task)
            .where(
                Task.status == "running",
                Task.lease_until < now,
                Task.kind.in_(kinds),
            )
            .with_for_update(skip_locked=True)
        )
    )
    for task in expired:
        task.revision += 1
        task.lease_token = None
        if task.external_state in {"submitted", "unknown"}:
            task.status, task.external_state = "reconciling", "unknown"
            task.error_code = "EXTERNAL_RESULT_UNKNOWN"
            db.execute(
                update(SearchUsage)
                .where(SearchUsage.task_id == task.id, SearchUsage.status == "submitted")
                .values(status="unknown")
            )
            db.execute(
                update(ResearchAction)
                .where(
                    ResearchAction.task_id == task.id,
                    ResearchAction.status == "submitted",
                )
                .values(status="unknown")
            )
        elif task.attempt_count >= settings.task_attempt_limit:
            task.status, task.error_code = "failed", "ATTEMPT_LIMIT_REACHED"
        else:
            task.status = "queued"
    db.flush()
    if on_recovery:
        for task in expired:
            on_recovery(db, task)
    candidates = select(Task.id).where(
        Task.status == "queued",
        Task.kind.in_(kinds),
        Task.attempt_count < settings.task_attempt_limit,
    )
    candidates = candidates.order_by(Task.created_at, Task.id).limit(1)
    if db.bind.dialect.name == "postgresql":
        candidates = candidates.with_for_update(skip_locked=True)
    task_id = db.scalar(candidates)
    if task_id is None:
        return None
    token = new_id()
    result = db.execute(
        update(Task)
        .where(Task.id == task_id, Task.status == "queued")
        .values(
            status="running",
            lease_token=token,
            lease_until=now + timedelta(seconds=settings.task_lease_seconds),
            attempt_count=Task.attempt_count + 1,
            revision=Task.revision + 1,
            started_at=now,
        )
    )
    return (task_id, token) if result.rowcount == 1 else None


def reserve_model(db: Session, task: Task, maximum_tokens: int):
    existing = db.get(ModelUsage, task.id)
    if existing:
        raise DomainError("EXTERNAL_RESULT_UNKNOWN", "该外部调用已有用量记录，请先核对")
    result = db.execute(
        update(Budget)
        .where(
            Budget.job_id == task.job_id,
            Budget.used + Budget.reserved < Budget.call_limit,
            Budget.tokens_used + Budget.tokens_reserved + maximum_tokens <= Budget.token_limit,
        )
        .values(
            reserved=Budget.reserved + 1, tokens_reserved=Budget.tokens_reserved + maximum_tokens
        )
    )
    if result.rowcount != 1:
        raise DomainError("BUDGET_EXCEEDED", "模型预算不足", 429)
    db.add(
        ModelUsage(
            task_id=task.id, job_id=task.job_id, reserved_tokens=maximum_tokens, status="reserved"
        )
    )


def settle_model(db: Session, task: Task, actual_tokens: int):
    usage = db.get(ModelUsage, task.id)
    if usage is None or usage.status != "reserved":
        raise DomainError("INVALID_STATE_TRANSITION", "预算记录状态不符")
    # Missing/untrusted usage retains the full reservation as consumption.
    charged = max(actual_tokens, 0) or usage.reserved_tokens
    db.execute(
        update(Budget)
        .where(Budget.job_id == task.job_id)
        .values(
            reserved=Budget.reserved - 1,
            used=Budget.used + 1,
            tokens_reserved=Budget.tokens_reserved - usage.reserved_tokens,
            tokens_used=Budget.tokens_used + charged,
        )
    )
    usage.status, usage.actual_tokens = "settled", charged


def fence(db: Session, task_id: str, token: str) -> Task:
    task = db.scalar(
        select(Task)
        .where(
            Task.id == task_id,
            Task.status == "running",
            Task.lease_token == token,
            or_(Task.lease_until.is_(None), and_(Task.lease_until > utcnow())),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if task is None:
        raise DomainError("STALE_TASK_LEASE", "任务执行权已失效")
    return task
