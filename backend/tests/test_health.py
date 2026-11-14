import pytest
from fastapi.testclient import TestClient

from app.core import database
from app.core.config import Settings
from app.main import create_app


def client_with_database(url: str | None = None) -> TestClient:
    settings = Settings(_env_file=None, database_url=url, environment="test")
    return TestClient(create_app(settings))


def test_liveness_does_not_claim_database_or_business_readiness():
    response = client_with_database().get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "cheeta-api",
        "stage": "initialization",
    }
    assert response.headers["X-Request-ID"]


def test_readiness_without_database_is_not_ready():
    response = client_with_database().get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "unavailable"


def test_database_errors_never_leak_credentials(monkeypatch: pytest.MonkeyPatch):
    secret_url = "postgresql+psycopg://example:private-test-password@invalid/cheeta"

    def fail(_settings):
        raise RuntimeError(secret_url)

    monkeypatch.setattr(database, "check_database", fail)
    response = client_with_database(secret_url).get("/api/v1/health/ready")
    assert response.status_code == 503
    assert "private-test-password" not in response.text
    assert "postgresql" not in response.text


def test_readiness_success_requires_database_probe(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(database, "check_database", lambda _settings: True)
    response = client_with_database("postgresql+psycopg://example:example@invalid/cheeta").get(
        "/api/v1/health/ready"
    )
    assert response.status_code == 200
    assert response.json()["checks"]["database"] == "ok"


def test_unknown_business_route_is_not_a_fake_success():
    response = client_with_database().get("/api/v1/not-implemented")
    assert response.status_code == 404
    assert response.json()["code"] == "HTTP_404"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_cors_does_not_grant_access_to_unconfigured_origin():
    response = client_with_database().get(
        "/api/v1/health", headers={"Origin": "https://untrusted.example"}
    )
    assert "Access-Control-Allow-Origin" not in response.headers


def test_anonymous_business_request_requires_login_before_database_configuration():
    response = client_with_database().get("/api/v1/jobs")
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"
