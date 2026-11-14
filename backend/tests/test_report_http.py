from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.main import create_app
from app.modules.outreach.models import OutreachArtifact, OutreachCase, ReportAudit


def test_review_export_audit_and_invalidation(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)

    def local_session(request):
        return Session(engine)

    monkeypatch.setattr("app.core.auth.database_session", local_session)
    monkeypatch.setattr("app.modules.outreach.router.database_session", local_session)
    with Session(engine) as session, session.begin():
        session.add(
            OutreachCase(
                id="case",
                organization_id="local-development",
                owner_id="local-reviewer",
                application_id="app",
                candidate_id="candidate",
                job_id="job",
                snapshot={"artifact_refs": {}},
                session_data={},
            )
        )
        session.add(
            OutreachArtifact(
                id="evaluation",
                case_id="case",
                type="D09",
                version=1,
                content={"conclusion": "recommended"},
                provenance={},
                input_refs=[],
            )
        )
        session.add(
            OutreachArtifact(
                id="report",
                case_id="case",
                type="D10",
                version=1,
                content={"content_markdown": "虚构推荐"},
                provenance={},
                input_refs=[{"id": "evaluation", "version": 1}],
            )
        )
    with TestClient(create_app(Settings(local_password=SecretStr("fixture-password")))) as client:
        headers = {"Origin": "http://localhost:5173"}
        login = client.post(
            "/api/v1/auth/login",
            headers=headers,
            json={"username": "local-reviewer", "password": "fixture-password"},
        )
        headers["X-CSRF-Token"] = login.json()["csrf_token"]
        download_headers = {"X-Export-Request-ID": "fixture-download-001"}
        url = "/api/v1/reports/report/export?version=1"
        assert client.get(url, headers=download_headers).status_code == 409
        with Session(engine) as session, session.begin():
            session.get(OutreachArtifact, "report").valid = True
            session.get(OutreachArtifact, "evaluation").valid = False
        assert client.get(url, headers=download_headers).status_code == 409
        with Session(engine) as session, session.begin():
            session.get(OutreachCase, "case").organization_id = "other-organization"
        assert client.get(url, headers=download_headers).status_code == 404
        with Session(engine) as session, session.begin():
            session.get(OutreachCase, "case").organization_id = "local-development"
            session.get(OutreachArtifact, "evaluation").valid = True
        assert (
            client.post(
                "/api/v1/reports/report/review",
                headers=headers,
                json={
                    "expected_version": 1,
                    "expected_revision": 1,
                    "action": "approve",
                    "reason": "人工检查虚构版本",
                },
            ).status_code
            == 200
        )
        for _ in range(2):
            response = client.get(url, headers=download_headers)
            assert response.status_code == 200
            assert response.text == "虚构推荐"
        with Session(engine) as session, session.begin():
            assert session.scalar(select(func.count()).select_from(ReportAudit)) == 2
            session.get(OutreachArtifact, "report").valid = False
        assert client.get(url, headers=download_headers).status_code == 409


def test_new_answer_invalidates_existing_approved_report(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)

    def local_session(request):
        return Session(engine)

    monkeypatch.setattr("app.core.auth.database_session", local_session)
    monkeypatch.setattr("app.modules.outreach.router.database_session", local_session)
    with Session(engine) as session, session.begin():
        session.add(
            OutreachCase(
                id="answer-case",
                organization_id="local-development",
                owner_id="local-reviewer",
                application_id="answer-app",
                candidate_id="answer-candidate",
                job_id="job",
                snapshot={"artifact_refs": {}},
                session_data={"current_question": {"id": "q", "question": "Fixture question"}},
                revision=1,
                status="in_progress",
                stop_status="none",
            )
        )
        for kind in ["D07", "D08", "D09", "D10"]:
            session.add(
                OutreachArtifact(
                    id="answer-" + kind,
                    case_id="answer-case",
                    type=kind,
                    version=1,
                    content={},
                    provenance={},
                    input_refs=[],
                    review_status="approved",
                    valid=True,
                )
            )
    with TestClient(create_app(Settings(local_password=SecretStr("fixture-password")))) as client:
        headers = {"Origin": "http://localhost:5173"}
        login = client.post(
            "/api/v1/auth/login",
            headers=headers,
            json={"username": "local-reviewer", "password": "fixture-password"},
        )
        headers["X-CSRF-Token"] = login.json()["csrf_token"]
        response = client.post(
            "/api/v1/calls/answer-case/answers",
            headers=headers,
            json={"expected_revision": 1, "answer": "Additional fictional evidence"},
        )
        assert response.status_code == 200
    with Session(engine) as session:
        assert session.get(OutreachArtifact, "answer-D07").valid
        for kind in ["D08", "D09", "D10"]:
            artifact = session.get(OutreachArtifact, "answer-" + kind)
            assert not artifact.valid and artifact.review_status == "expired"
        assert len(session.get(OutreachCase, "answer-case").session_data["answers"]) == 1
