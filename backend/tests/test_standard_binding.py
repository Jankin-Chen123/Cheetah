from fastapi.testclient import TestClient
from outreach_fixtures import reviewer_app
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.modules.outreach.models import OutreachArtifact, OutreachCase
from app.modules.outreach.templates import bind_templates


def test_standard_binding_permissions_versions_and_invalidation(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.core.auth.database_session", lambda request: Session(engine))
    monkeypatch.setattr(
        "app.modules.outreach.router.database_session", lambda request: Session(engine)
    )
    with Session(engine) as session, session.begin():
        for case_id, organization in [("case", "local-development"), ("other", "other")]:
            session.add(
                OutreachCase(
                    id=case_id,
                    organization_id=organization,
                    owner_id="local-reviewer",
                    application_id=case_id,
                    candidate_id=case_id,
                    job_id="job",
                    snapshot={"fixture_only": True},
                    session_data={},
                    revision=1,
                )
            )
        for kind in ["D07", "D08", "D09", "D10"]:
            session.add(
                OutreachArtifact(
                    id=kind,
                    case_id="case",
                    type=kind,
                    version=1,
                    content={},
                    provenance={},
                    input_refs=[],
                    valid=True,
                    review_status="approved",
                )
            )
    standard = {
        "job_id": "job",
        "version": 1,
        "status": "confirmed",
        "confirmed_by": "untrusted",
        "dimensions": [
            {
                "id": "ability",
                "label": "岗位能力",
                "indicators": "个人行为案例",
                "weight_percent": 100,
                "source_refs": ["fixture-job-p1"],
                "anchors": {band: "虚构行为锚点" for band in ["1-2", "3-4", "5-6", "7-8", "9-10"]},
            }
        ],
    }
    payload = {
        "expected_revision": 1,
        "standard": standard,
        "threshold": 8,
        "report_template_version": 1,
    }
    with TestClient(reviewer_app(engine, Settings())) as client:
        url = "/api/v1/calls/case/evaluation-standard"
        assert client.post(url, json=payload).status_code == 401
        headers = {"Origin": "http://localhost:5173"}
        login = client.post(
            "/api/v1/auth/login",
            headers=headers,
            json={
                "username": "local-reviewer",
                "password": "fixture-password",
            },
        )
        assert client.post(url, headers=headers, json=payload).status_code == 403
        headers["X-CSRF-Token"] = login.json()["csrf_token"]
        assert (
            client.post(
                "/api/v1/calls/other/evaluation-standard", headers=headers, json=payload
            ).status_code
            == 404
        )
        wrong_job = {**payload, "standard": {**standard, "job_id": "wrong"}}
        assert client.post(url, headers=headers, json=wrong_job).status_code == 409
        assert client.post(url, headers=headers, json=payload).json() == {
            "revision": 2,
            "standard_version": 1,
        }
        assert client.post(url, headers=headers, json=payload).status_code == 409
        assert (
            client.post(url, headers=headers, json={**payload, "expected_revision": 2}).status_code
            == 409
        )
        upgraded = {**payload, "expected_revision": 2, "standard": {**standard, "version": 2}}
        assert client.post(url, headers=headers, json=upgraded).status_code == 200
    with Session(engine) as session:
        case = session.get(OutreachCase, "case")
        assert case.revision == 3
        assert (
            case.session_data["job_interview_standard"]["standard"]["confirmed_by"]
            == "local-reviewer"
        )
        assert len(case.session_data["evaluation_binding_history"]) == 1
        assert bind_templates(case, Settings(), "D09")["content"]["score_scale"] == "1-10"
        assert session.get(OutreachArtifact, "D08").valid
        for kind in ["D07", "D09", "D10"]:
            assert not session.get(OutreachArtifact, kind).valid
            assert session.get(OutreachArtifact, kind).review_status == "expired"
        # Stored standards retain Decimal weights in JSON-safe form.
        assert (
            case.session_data["job_interview_standard"]["standard"]["dimensions"][0][
                "weight_percent"
            ]
            == "100"
        )
