"""Poll persisted D07/followup tasks. No real telephone transport is invoked."""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import get_engine  # noqa: E402
from app.modules.outreach.followup_worker import execute_followup  # noqa: E402
from app.modules.outreach.minutes_worker import execute_minutes  # noqa: E402
from app.modules.outreach.models import ModelStep  # noqa: E402
from app.modules.outreach.report_worker import execute_report_step  # noqa: E402
from app.modules.outreach.steps import recover_stale_steps  # noqa: E402
from app.modules.outreach.worker import execute_outline  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if settings.database_url is None:
        parser.error("CHEETA_DATABASE_URL is required")
    engine = get_engine(settings.database_url.get_secret_value())
    while True:
        with Session(engine) as session, session.begin():
            recover_stale_steps(session)
        with Session(engine) as session:
            task = session.scalar(
                select(ModelStep)
                .where(
                    ModelStep.status == "queued",
                    ModelStep.step.in_(["D07", "followup", "D08", "D09", "D10"]),
                )
                .order_by(ModelStep.id)
                .limit(1)
            )
            task_id, step = (task.id, task.step) if task else (None, None)
        if task_id:
            executor = {
                "D07": execute_outline,
                "followup": execute_followup,
                "D08": execute_minutes,
                "D09": execute_report_step,
                "D10": execute_report_step,
            }[step]
            executor(engine, settings, task_id)
        if args.once:
            break
        if task_id is None:
            time.sleep(1)


if __name__ == "__main__":
    main()
