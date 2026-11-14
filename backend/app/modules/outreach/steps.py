"""Durable step receipt operations; scheduling is handled separately."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.outreach.models import ModelStep, OutreachCase


def register_step(session: Session, case_id: str, step: str, revision: int):
    existing = session.scalar(
        select(ModelStep).where(
            ModelStep.case_id == case_id,
            ModelStep.step == step,
            ModelStep.input_revision == revision,
        )
    )
    if existing:
        return existing, False
    receipt = ModelStep(
        id=uuid4().hex,
        case_id=case_id,
        step=step,
        input_revision=revision,
        status="queued",
        detail={"registered_at": datetime.now(UTC).isoformat()},
    )
    session.add(receipt)
    session.flush()
    return receipt, True


def finish_step(
    receipt: ModelStep, *, result_ref: dict | None = None, error_code: str | None = None
):
    if receipt.status in {"completed", "failed", "cancelled"}:
        raise ValueError("STEP_ALREADY_TERMINAL")
    receipt.status = "failed" if error_code else "completed"
    receipt.detail = {
        **receipt.detail,
        "finished_at": datetime.now(UTC).isoformat(),
        "result_ref": result_ref,
        "error_code": error_code,
    }


def claim_step(session: Session, task_id: str):
    task = session.scalar(
        select(ModelStep)
        .where(ModelStep.id == task_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if task is None:
        raise LookupError("Task not found")
    if task.status != "queued":
        return None
    case = session.scalar(
        select(OutreachCase)
        .where(OutreachCase.id == task.case_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if case is None or case.revision != task.input_revision:
        task.status = "cancelled"
        task.detail = {**task.detail, "error_code": "INPUT_VERSION_CHANGED"}
        return None
    if task.step in {"D07", "followup"} and case.stop_status != "none":
        task.status = "cancelled"
        task.detail = {**task.detail, "error_code": "INTERVIEW_STOPPED"}
        return None
    task.status = "running"
    task.detail = {**task.detail, "started_at": datetime.now(UTC).isoformat()}
    return {
        "case_id": case.id,
        "input_revision": case.revision,
        "snapshot": case.snapshot,
        "session_data": case.session_data,
    }


def result_still_current(task: ModelStep, case: OutreachCase) -> bool:
    if task.status != "running" or case.revision != task.input_revision:
        return False
    return task.step not in {"D07", "followup"} or case.stop_status == "none"


def recover_stale_steps(session: Session, *, older_than_seconds: int = 180):
    if older_than_seconds < 120:
        raise ValueError("Recovery interval must exceed the bounded model timeout")
    recovered = 0
    now = datetime.now(UTC)
    tasks = session.scalars(
        select(ModelStep).where(ModelStep.status == "running").with_for_update(skip_locked=True)
    )
    for task in tasks:
        started = task.detail.get("started_at")
        if not started:
            continue
        elapsed = (now - datetime.fromisoformat(started)).total_seconds()
        if elapsed < older_than_seconds:
            continue
        finish_step(task, error_code="WORKER_INTERRUPTED_REVIEW_REQUIRED")
        recovered += 1
    return recovered


def retry_step(task: ModelStep, case: OutreachCase, actor_id: str):
    if task.step.startswith("briefing_email_"):
        raise ValueError("MAIL_REQUIRES_RECONCILIATION")
    if task.status != "failed":
        raise ValueError("ONLY_FAILED_INTERNAL_STEP_RETRYABLE")
    if task.detail.get("error_code") == "WORKER_INTERRUPTED_REVIEW_REQUIRED":
        raise ValueError("INTERRUPTED_ATTEMPT_REQUIRES_RECONCILIATION")
    if task.case_id != case.id or task.input_revision != case.revision:
        raise ValueError("INPUT_VERSION_CHANGED")
    if task.step in {"D07", "followup"} and case.stop_status != "none":
        raise ValueError("INTERVIEW_STOPPED")
    count = task.detail.get("retry_count", 0)
    if count >= 3:
        raise ValueError("RETRY_LIMIT_EXCEEDED")
    history = [
        *task.detail.get("failure_history", []),
        {
            "error_code": task.detail.get("error_code"),
            "finished_at": task.detail.get("finished_at"),
            "retried_by": actor_id,
            "retried_at": datetime.now(UTC).isoformat(),
        },
    ]
    task.status = "queued"
    task.detail = {
        **task.detail,
        "retry_count": count + 1,
        "failure_history": history,
        "error_code": None,
        "finished_at": None,
    }
