"""Poll persisted D07/followup tasks. No real telephone transport is invoked."""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import or_, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import get_engine  # noqa: E402
from app.modules.outreach.briefing_mail import execute_briefing_mail  # noqa: E402
from app.modules.outreach.conversation_worker import execute_conversation  # noqa: E402
from app.modules.outreach.followup_worker import execute_followup  # noqa: E402
from app.modules.outreach.minutes_worker import execute_minutes  # noqa: E402
from app.modules.outreach.models import ModelStep  # noqa: E402
from app.modules.outreach.postprocessing import schedule_postprocessing  # noqa: E402
from app.modules.outreach.report_worker import execute_report_step  # noqa: E402
from app.modules.outreach.steps import finish_step, recover_stale_steps  # noqa: E402
from app.modules.outreach.worker import execute_outline  # noqa: E402


def execute_safely(executor, engine, settings, task_id):
    try:
        executor(engine, settings, task_id)
    except Exception as error:
        with Session(engine) as session, session.begin():
            task = session.get(ModelStep, task_id, with_for_update=True)
            if task and task.status in {"queued", "running"}:
                task.detail = {**task.detail, "failure_type": type(error).__name__}
                finish_step(task, error_code="WORKER_EXECUTION_FAILED")
        print("Worker task failed: " + type(error).__name__, file=sys.stderr, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--case-id", help="Limit recovery, scheduling and execution to this case")
    args = parser.parse_args()
    settings = get_settings()
    if settings.database_url is None:
        parser.error("CHEETA_DATABASE_URL is required")
    engine = get_engine(settings.database_url.get_secret_value())
    while True:
        with Session(engine) as session, session.begin():
            from app.modules.outreach.intake_handoff import consume_pending

            if args.case_id is None:
                consume_pending(session)
            recover_stale_steps(
                session,
                case_id=args.case_id,
                outline_timeout_seconds=4 * settings.model_timeout_seconds + 60
                if settings.text_provider == "configured"
                else 300,
            )
            schedule_postprocessing(session, case_id=args.case_id)
        with Session(engine) as session:
            task = session.scalar(
                select(ModelStep)
                .where(
                    ModelStep.status == "queued",
                    ModelStep.case_id == args.case_id if args.case_id else True,
                    or_(
                        ModelStep.step.in_(
                            ["D07", "followup", "conversation", "D08", "D09", "D10"]
                        ),
                        ModelStep.step.like("briefing_email_%"),
                    ),
                )
                .order_by(ModelStep.id)
                .limit(1)
            )
            task_id, step = (task.id, task.step) if task else (None, None)
        if task_id:
            executor = (
                execute_briefing_mail
                if step.startswith("briefing_email_")
                else {
                    "D07": execute_outline,
                    "followup": execute_followup,
                    "conversation": execute_conversation,
                    "D08": execute_minutes,
                    "D09": execute_report_step,
                    "D10": execute_report_step,
                }[step]
            )
            execute_safely(executor, engine, settings, task_id)
        if args.once:
            break
        if task_id is None:
            time.sleep(0.2)


if __name__ == "__main__":
    main()
