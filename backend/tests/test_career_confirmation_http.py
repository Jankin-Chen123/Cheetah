from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.main import create_app
from app.modules.outreach.models import OutreachArtifact, OutreachCase


def test_confirm_requires_owner_csrf_and_current_revision(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.core.auth.database_session", lambda request: Session(engine))
    monkeypatch.setattr(
        "app.modules.outreach.router.database_session", lambda request: Session(engine)
    )
    with Session(engine) as db, db.begin():
        for cid, owner in [("mine", "local-reviewer"), ("other", "another-owner")]:
            db.add(
                OutreachCase(
                    id=cid,
                    organization_id="local-development",
                    owner_id=owner,
                    application_id=cid,
                    candidate_id=cid,
                    job_id="job",
                    snapshot={"artifact_refs": {}},
                    session_data={
                        "answers": [{"id": "a", "text": "目前在虚构城市", "version": 1}],
                        "upstream_content": {"D03": {}},
                    },
                )
            )
        db.flush()
        db.add(
            OutreachArtifact(
                id="minutes",
                case_id="mine",
                type="D08",
                version=1,
                content={"conflicts": []},
                provenance={},
                input_refs=[],
            )
        )
        db.add(
            OutreachArtifact(
                id="evaluation",
                case_id="mine",
                type="D09",
                version=1,
                content={
                    "dimensions": [
                        {
                            "dimension_id": "one",
                            "label": "虚构能力",
                            "score": None,
                            "weight_percent": 100,
                            "weighted_score": None,
                            "scoring_anchors": {"7-8": "虚构锚点"},
                            "reason": "证据不足",
                        }
                    ],
                    "total_score": None,
                    "scored_weight_percent": 0,
                    "conclusion": "insufficient",
                },
                provenance={"source_mode": "mock"},
                input_refs=[],
            )
        )
        db.add(
            OutreachArtifact(
                id="other-evaluation",
                case_id="other",
                type="D09",
                version=1,
                content={},
                provenance={},
                input_refs=[],
            )
        )
    body = dict(
        expected_revision=1,
        minutes_id="minutes",
        minutes_version=1,
        field_path="profile.current_city",
        value="虚构城市",
        answer_id="a",
        quote="目前在虚构城市",
        reason="核对本次口述",
    )
    with TestClient(create_app(Settings(local_password=SecretStr("fixture-password")))) as client:
        path = "/api/v1/calls/mine/career-confirmations"
        assert client.post(path, json=body).status_code in {401, 403}
        headers = {"Origin": "http://localhost:5173"}
        login = client.post(
            "/api/v1/auth/login",
            headers=headers,
            json={"username": "local-reviewer", "password": "fixture-password"},
        )
        assert client.post(path, headers=headers, json=body).status_code == 403
        headers["X-CSRF-Token"] = login.json()["csrf_token"]
        assert (
            client.get("/api/v1/evaluations/other-evaluation/export?version=1").status_code == 404
        )
        assert client.get("/api/v1/evaluations/evaluation/export?version=2").status_code == 409
        exported = client.get("/api/v1/evaluations/evaluation/export?version=1")
        assert exported.status_code == 200
        from io import BytesIO
        from zipfile import ZipFile

        xml = ZipFile(BytesIO(exported.content)).read("word/document.xml").decode()
        assert "内部面试评估" in xml and "未评估" in xml and "虚构能力" in xml
        assert "<w:tbl>" in xml
        with Session(engine) as db, db.begin():
            db.get(OutreachArtifact, "evaluation").valid = False
        assert client.get("/api/v1/evaluations/evaluation/export?version=1").status_code == 409
        assert (
            client.post(path.replace("mine", "other"), headers=headers, json=body).status_code
            == 404
        )
        response = client.post(path, headers=headers, json=body)
        assert response.status_code == 200
        receipt = response.json()["confirmation"]
        assert client.post(path, headers=headers, json=body).status_code == 409
        current = client.get("/api/v1/calls/mine").json()
        assert (
            current["session"]["career_confirmed_upstream"]["D03"]["profile"]["current_city"]
            == "虚构城市"
        )
        assert current["session"]["active_career_confirmation_ids"] == [receipt["id"]]
        revoked = client.post(
            path + "/" + receipt["id"] + "/revoke",
            headers=headers,
            json={"expected_revision": 2, "reason": "需重新确认"},
        )
        assert revoked.status_code == 200
        assert (
            client.get("/api/v1/calls/mine").json()["session"]["active_career_confirmation_ids"]
            == []
        )
