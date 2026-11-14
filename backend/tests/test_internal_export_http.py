from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.main import create_app
from app.modules.outreach.models import OutreachArtifact, OutreachCase


def test_outline_limitations_review_http(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    for module in ("app.core.auth", "app.modules.outreach.router"):
        monkeypatch.setattr(f"{module}.database_session", lambda request: Session(engine))
    with Session(engine) as db, db.begin():
        db.add(
            OutreachCase(
                id="case",
                organization_id="local-development",
                owner_id="local-reviewer",
                application_id="application",
                candidate_id="candidate",
                job_id="job",
                snapshot={"fixture_only": True},
                session_data={"outline_id": "outline"},
            )
        )
        db.flush()
        db.add(
            OutreachArtifact(
                id="outline",
                case_id="case",
                type="D07",
                version=2,
                content={"readiness": "READY_WITH_LIMITATIONS", "readiness_reasons": ["缺口"]},
                provenance={},
                input_refs=[],
            )
        )
    origin = {"Origin": "http://localhost:5173"}
    path = "/api/v1/calls/case/outline-limitations-review"
    body = {"expected_revision": 1, "expected_version": 2, "rationale": "已核对缺口"}
    settings = Settings(
        local_password=SecretStr("fictional-password"), allowed_origins=[origin["Origin"]]
    )
    with TestClient(create_app(settings)) as client:
        assert client.post(path, headers=origin, json=body).status_code == 401
        login = client.post(
            "/api/v1/auth/login",
            headers=origin,
            json={"username": "local-reviewer", "password": "fictional-password"},
        )
        assert client.post(path, headers=origin, json=body).status_code == 403
        headers = {**origin, "X-CSRF-Token": login.json()["csrf_token"]}
        with Session(engine) as db, db.begin():
            db.get(OutreachCase, "case").owner_id = "other"
        assert client.post(path, headers=headers, json=body).status_code == 404
        with Session(engine) as db, db.begin():
            db.get(OutreachCase, "case").owner_id = "local-reviewer"
        stale = client.post(path, headers=headers, json={**body, "expected_version": 1})
        assert stale.status_code == 409
        assert stale.json()["code"] == "OUTLINE_REGENERATION_REQUIRED"
        response = client.post(path, headers=headers, json=body)
        assert response.status_code == 200
        assert response.json()["review"]["outline_version"] == 2
        assert response.json()["review"]["reviewer_id"] == "local-reviewer"
        assert client.post(path, headers=headers, json=body).json()["code"] == "VERSION_CONFLICT"


@pytest.mark.parametrize(
    ("category", "kind", "artifact_type", "title"),
    [
        ("outlines", "outline", "D07", "内部面试准备稿"),
        ("minutes", "minutes", "D08", "内部面试信息提取"),
    ],
)
def test_internal_export_is_scoped_to_owner_type_and_version(
    monkeypatch, category, kind, artifact_type, title
):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        "app.modules.outreach.router.database_session", lambda request: Session(engine)
    )
    identity = {"organization_id": "org", "user_id": "reader"}
    monkeypatch.setattr("app.modules.outreach.router.require_identity", lambda request: identity)

    with Session(engine) as db, db.begin():
        db.add(
            OutreachCase(
                id="case",
                organization_id="org",
                owner_id="reader",
                application_id="application",
                candidate_id="candidate",
                job_id="job",
                snapshot={},
                session_data={},
            )
        )
        db.flush()
        for artifact_id, type_ in [("requested", artifact_type), ("different", "D09")]:
            db.add(
                OutreachArtifact(
                    id=artifact_id,
                    case_id="case",
                    type=type_,
                    version=1,
                    content={},
                    provenance={},
                    input_refs=[],
                )
            )

    with TestClient(create_app(Settings())) as client:
        path = f"/api/v1/{category}/requested/export"
        assert (
            client.get(path.replace("requested", "different"), params={"version": 1}).status_code
            == 404
        )
        result = client.get(path, params={"version": 2})
        assert result.status_code == 409
        assert f"{kind.upper()}_VERSION_INVALID" in result.text

        result = client.get(path, params={"version": 1})
        assert result.status_code == 200
        assert result.headers["cache-control"] == "no-store"
        assert f"internal-{kind}-v1.docx" in result.headers["content-disposition"]
        with ZipFile(BytesIO(result.content)) as document:
            assert title in document.read("word/document.xml").decode()

        identity["user_id"] = "other"
        assert client.get(path, params={"version": 1}).status_code == 404
        identity["user_id"] = "reader"
        with Session(engine) as db, db.begin():
            db.get(OutreachArtifact, "requested").valid = False
        assert client.get(path, params={"version": 1}).status_code == 409
