from fastapi.testclient import TestClient
from outreach_fixtures import reviewer_app
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base


def test_fixture_batches_replay_and_preserve_history(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)

    def local_session(request):
        return Session(engine)

    monkeypatch.setattr("app.core.auth.database_session", local_session)
    monkeypatch.setattr("app.modules.outreach.router.database_session", local_session)
    with TestClient(reviewer_app(engine, Settings())) as client:
        headers = {"Origin": "http://localhost:5173"}
        login = client.post(
            "/api/v1/auth/login",
            headers=headers,
            json={"username": "local-reviewer", "password": "fixture-password"},
        )
        headers["X-CSRF-Token"] = login.json()["csrf_token"]

        def create(body):
            response = client.post("/api/v1/dev/fixture", headers=headers, json=body)
            assert response.status_code == 200
            return response.json()

        old = create({})
        a = create({"batch": "run-a"})
        assert create({"batch": "run-a"})["id"] == a["id"]
        assert create({"batch": "run-b"})["id"] not in {a["id"], old["id"]}
        assert create({})["id"] == old["id"]
        assert (
            client.post(
                "/api/v1/dev/fixture", headers=headers, json={"batch": "../bad"}
            ).status_code
            == 422
        )
