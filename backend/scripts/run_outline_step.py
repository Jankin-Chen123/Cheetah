"""Execute one registered D07 task; never initiates telephone transport."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.database import get_engine  # noqa: E402
from app.modules.outreach.followup_worker import execute_followup  # noqa: E402
from app.modules.outreach.worker import execute_outline  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("--step", choices=["D07", "followup"], default="D07")
    args = parser.parse_args()
    settings = get_settings()
    if settings.database_url is None:
        parser.error("CHEETA_DATABASE_URL is required")
    executor = execute_outline if args.step == "D07" else execute_followup
    executor(get_engine(settings.database_url.get_secret_value()), settings, args.task_id)
    print("Step processed; inspect task status for the actual outcome")


if __name__ == "__main__":
    main()
