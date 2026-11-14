"""Persist fictional configuration snapshots and verify them using a new connection."""

import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.core.database import get_engine  # noqa: E402
from app.modules.outreach.models import OutreachCase  # noqa: E402
from app.modules.outreach.templates import bind_templates  # noqa: E402


def main():
    settings = Settings()
    if settings.database_url is None:
        raise RuntimeError("Local PostgreSQL configuration required")
    engine = get_engine(settings.database_url.get_secret_value())
    if engine.dialect.name != "postgresql":
        raise RuntimeError("PostgreSQL required")
    marker = "fixture-templates-" + uuid4().hex
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
        expected = {step: bind_templates(case, settings, step) for step in ("D09", "D10")}
    engine.dispose()
    # Invalid replacement paths prove that the stored snapshots are used on reload.
    changed = Settings(
        evaluation_template_path=Path("nonexistent-evaluation.json"),
        report_template_path=Path("nonexistent-report.json"),
    )
    with Session(engine) as session:
        case = session.get(OutreachCase, marker)
        for step, bound in expected.items():
            if bind_templates(case, changed, step) != bound:
                raise RuntimeError("Persisted snapshot changed")
    print("PostgreSQL: D09/D10 content and SHA256 survive connection disposal and reload")


if __name__ == "__main__":
    main()
