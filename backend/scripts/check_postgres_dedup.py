"""Local PostgreSQL concurrency check using explicitly fictional, isolated records."""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.contracts import ScreeningPassedEvent  # noqa: E402
from app.core.database import get_engine  # noqa: E402
from app.modules.outreach.models import OutreachCase, ReceivedEvent  # noqa: E402
from app.modules.outreach.service import consume_fixture  # noqa: E402


def main():
    settings = get_settings()
    if settings.database_url is None:
        raise RuntimeError("Local database configuration required")
    engine = get_engine(settings.database_url.get_secret_value())
    if engine.dialect.name != "postgresql":
        raise RuntimeError("This check requires PostgreSQL")
    root = Path(__file__).resolve().parents[2]
    payload = json.loads(
        (root / "docs/contracts/day1_screening_passed.example.json").read_text(encoding="utf8")
    )
    marker = "fixture-concurrency-" + uuid4().hex
    payload.update(organization_id=marker, event_id=marker, application_id=marker)
    event = ScreeningPassedEvent.model_validate(payload)

    def consume(_):
        with Session(engine) as session, session.begin():
            return consume_fixture(session, event, "fixture-check-owner").id

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(consume, range(8)))
    with Session(engine) as session:
        cases = session.scalar(
            select(func.count())
            .select_from(OutreachCase)
            .where(OutreachCase.organization_id == marker)
        )
        events = session.scalar(
            select(func.count())
            .select_from(ReceivedEvent)
            .where(ReceivedEvent.organization_id == marker)
        )
    if len(set(ids)) != 1 or cases != 1 or events != 1:
        raise RuntimeError("Concurrent dedup verification failed")
    print("PostgreSQL: 8 concurrent deliveries, 1 event receipt, 1 call task; no dialing")


if __name__ == "__main__":
    main()
