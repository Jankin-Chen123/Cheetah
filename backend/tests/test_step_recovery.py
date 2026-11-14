from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.modules.outreach.models import ModelStep, OutreachCase
from app.modules.outreach.steps import recover_stale_steps, retry_step


def test_retry_preserves_failure_history_and_is_bounded():
    case = OutreachCase(id="case", revision=2, stop_status="none")
    task = ModelStep(
        case_id="case",
        input_revision=2,
        step="D07",
        status="failed",
        detail={"error_code": "MODEL_NOT_CONFIGURED"},
    )
    retry_step(task, case, "reviewer")
    assert task.status == "queued"
    assert task.detail["failure_history"][0]["error_code"] == "MODEL_NOT_CONFIGURED"
    with pytest.raises(ValueError, match="ONLY_FAILED"):
        retry_step(task, case, "reviewer")
    task.status = "failed"
    task.detail = {**task.detail, "retry_count": 3}
    with pytest.raises(ValueError, match="LIMIT"):
        retry_step(task, case, "reviewer")
    task.detail = {"error_code": "WORKER_INTERRUPTED_REVIEW_REQUIRED"}
    with pytest.raises(ValueError, match="RECONCILIATION"):
        retry_step(task, case, "reviewer")


def test_stale_running_becomes_explicit_failure_without_reexecution():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        session.add(
            ModelStep(
                id="stale",
                case_id="case",
                step="D07",
                input_revision=1,
                status="running",
                detail={"started_at": (datetime.now(UTC) - timedelta(seconds=200)).isoformat()},
            )
        )
        session.add(
            ModelStep(
                id="recent",
                case_id="case",
                step="D08",
                input_revision=1,
                status="running",
                detail={"started_at": datetime.now(UTC).isoformat()},
            )
        )
        session.flush()
        assert recover_stale_steps(session) == 1
        assert session.get(ModelStep, "stale").status == "failed"
        assert session.get(ModelStep, "recent").status == "running"
        assert recover_stale_steps(session) == 0
