"""Local fictional report approval race and invalidation check; no external delivery."""

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import get_engine  # noqa: E402
from app.modules.outreach.artifacts import (  # noqa: E402
    export_markdown,
    invalidate_downstream,
    locked_case,
    review_report,
    save_artifact,
)
from app.modules.outreach.models import OutreachArtifact, OutreachCase  # noqa: E402


def main():
    settings = get_settings()
    if settings.database_url is None:
        raise RuntimeError("Local PostgreSQL configuration required")
    engine = get_engine(settings.database_url.get_secret_value())
    if engine.dialect.name != "postgresql":
        raise RuntimeError("PostgreSQL required")
    marker = "fixture-review-" + uuid4().hex
    with Session(engine) as session, session.begin():
        case = OutreachCase(
            id=marker,
            organization_id=marker,
            owner_id="fixture-owner",
            application_id=marker,
            candidate_id=marker,
            job_id=marker,
            snapshot={"fixture_only": True},
            session_data={},
        )
        session.add(case)
        session.flush()
        evaluation = save_artifact(
            session, case, "D09", {"conclusion": "recommended"}, {"source_mode": "mock"}, []
        )
        report = save_artifact(
            session,
            case,
            "D10",
            {"content_markdown": "虚构并发验收报告"},
            {"source_mode": "mock"},
            [{"id": evaluation.id, "version": 1}],
        )
        report_id = report.id

    def approve(_):
        with Session(engine) as session, session.begin():
            locked_case(session, marker, marker, "fixture-owner")
            report = session.get(OutreachArtifact, report_id, with_for_update=True)
            try:
                review_report(report, 1, 1, "approve", "fixture-owner", "并发验收")
                return "approved"
            except ValueError:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(approve, range(2)))
    if sorted(outcomes) != ["approved", "conflict"]:
        raise RuntimeError("Approval race failed")
    with Session(engine) as session, session.begin():
        case = locked_case(session, marker, marker, "fixture-owner")
        invalidate_downstream(session, case, "D08")
    with Session(engine) as session:
        try:
            export_markdown(session.get(OutreachArtifact, report_id))
        except ValueError:
            print("PostgreSQL: one approval, one revision conflict; correction blocks old export")
        else:
            raise RuntimeError("Invalidated report export was not blocked")


if __name__ == "__main__":
    main()
