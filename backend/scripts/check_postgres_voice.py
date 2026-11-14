"""Persisted fictional call transitions; never contacts a telephone provider."""

import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import get_engine  # noqa: E402
from app.modules.outreach.answers import request_stop  # noqa: E402
from app.modules.outreach.artifacts import locked_case  # noqa: E402
from app.modules.outreach.models import OutreachCase  # noqa: E402
from app.modules.outreach.voice import confirm_mock_stop, mock_callback, start_mock  # noqa: E402


def main():
    settings = get_settings()
    if settings.database_url is None:
        raise RuntimeError("Local PostgreSQL configuration required")
    engine = get_engine(settings.database_url.get_secret_value())
    if engine.dialect.name != "postgresql":
        raise RuntimeError("PostgreSQL required")
    marker = "fixture-voice-" + uuid4().hex
    with Session(engine) as session, session.begin():
        session.add(
            OutreachCase(
                id=marker,
                organization_id=marker,
                owner_id="fixture-owner",
                application_id=marker,
                candidate_id=marker,
                job_id=marker,
                snapshot={"fixture_only": True},
                session_data={"outline_id": "isolated-test-double"},
            )
        )
    with Session(engine) as session, session.begin():
        case = locked_case(session, marker, marker, "fixture-owner")
        start_mock(case, case.revision)
        start_mock(case, case.revision)
        assert len(case.session_data["attempts"]) == 1
        mock_callback(case, "event-2", 2, "in_progress")
        revision = case.revision
        mock_callback(case, "event-1", 1, "completed")
        assert case.revision == revision
        request_stop(case, case.revision)
    engine.dispose()
    with Session(engine) as session, session.begin():
        case = locked_case(session, marker, marker, "fixture-owner")
        assert case.stop_status == "requested"
        confirm_mock_stop(case)
    engine.dispose()
    with Session(engine) as session:
        case = session.get(OutreachCase, marker)
        assert case.stop_status == "confirmed" and case.status == "ended"
        assert len(case.session_data["attempts"]) == 1
        revision = case.revision
        mock_callback(case, "late", 3, "in_progress")
        assert case.revision == revision
        assert case.session_data["attempts"][0]["status"] == "completed"
    print(
        "PostgreSQL mock only: one attempt, stale callback ignored; "
        "requested/confirmed persisted, late callback ignored"
    )


if __name__ == "__main__":
    main()
