from fastapi.testclient import TestClient
from outreach_fixtures import reviewer_app
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base


def test_cookie_csrf_origin_and_logout(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)

    def session_for_request(request):
        return Session(engine)

    monkeypatch.setattr("app.core.auth.database_session", session_for_request)
    app = reviewer_app(engine, Settings())
    with TestClient(app) as client:
        assert client.get("/api/v1/auth/me").status_code == 401
        data = {"username": "local-reviewer", "password": "fixture-password"}
        assert client.post("/api/v1/auth/login", json=data).status_code == 403
        headers = {"Origin": "http://localhost:5173"}
        response = client.post("/api/v1/auth/login", json=data, headers=headers)
        assert response.status_code == 200
        assert "httponly" in response.headers["set-cookie"].lower()
        assert client.get("/api/v1/auth/me").status_code == 200
        assert client.post("/api/v1/auth/logout", headers=headers).status_code == 403
        headers["X-CSRF-Token"] = response.json()["csrf_token"]
        assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
        assert client.get("/api/v1/auth/me").status_code == 401
