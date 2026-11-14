from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import verify_password
from app.core.models import Identity, LoginSession, utcnow
from app.main import create_app

ORIGIN = {"Origin": "http://localhost:5173"}
ACCOUNT = {
    "username": "fixture-new-account",
    "display_name": "虚构注册用户",
    "password": "fixture-registration-password",
}


def test_registration_login_logout_and_password_storage(runtime):
    with TestClient(create_app(runtime[0])) as client:
        assert client.get("/api/v1/auth/me").status_code == 401
        registered = client.post("/api/v1/auth/register", json=ACCOUNT, headers=ORIGIN)
        assert registered.status_code == 201, registered.text
        session = registered.json()
        assert session["user"]["display_name"] == ACCOUNT["display_name"]
        assert "HttpOnly" in registered.headers["set-cookie"]
        assert "SameSite=lax" in registered.headers["set-cookie"]
        assert ACCOUNT["password"] not in registered.text
        assert client.get("/api/v1/auth/me").json()["user"] == session["user"]
        assert client.post("/api/v1/auth/logout", headers=ORIGIN).status_code == 403
        assert (
            client.post(
                "/api/v1/auth/logout",
                headers={**ORIGIN, "X-CSRF-Token": session["csrf_token"]},
            ).status_code
            == 204
        )
        assert client.get("/api/v1/auth/me").status_code == 401
        logged_in = client.post(
            "/api/v1/auth/login",
            json={"username": ACCOUNT["username"], "password": ACCOUNT["password"]},
            headers=ORIGIN,
        )
        assert logged_in.status_code == 200
        assert logged_in.json()["user"] == session["user"]
        with Session(runtime[1]) as db:
            user = db.get(Identity, session["user"]["id"])
            assert user.password_hash != ACCOUNT["password"]
            assert verify_password(ACCOUNT["password"], user.password_hash)
            assert user.organization_id == session["organization"]["id"]


def test_registration_isolates_organizations_and_rotates_existing_session(api, runtime):
    old_cookie = api.cookies.get("cheetah_session")
    old_user = api.get("/api/v1/auth/me").json()
    created = api.post(
        "/api/v1/jobs",
        json={"material_text": "虚构岗位需求"},
        headers={"Idempotency-Key": "fixture-registration-isolation"},
    )
    assert created.status_code == 201
    result = api.post("/api/v1/auth/register", json=ACCOUNT)
    assert result.status_code == 201
    assert result.json()["organization"] != old_user["organization"]
    assert api.get(f"/api/v1/jobs/{created.json()['id']}").status_code == 404
    with TestClient(create_app(runtime[0])) as previous:
        previous.cookies.set("cheetah_session", old_cookie)
        assert previous.get("/api/v1/auth/me").status_code == 401


@pytest.mark.parametrize(
    "change",
    [
        {"username": "ab"},
        {"username": " contains space"},
        {"username": "不合法账号"},
        {"password": "too-short"},
        {"password": "x" * 129},
        {"display_name": "   "},
        {"organization_id": "fixture-org"},
        {"permissions": ["admin"]},
    ],
)
def test_registration_rejects_invalid_fields_and_injected_permissions(runtime, change):
    with TestClient(create_app(runtime[0])) as client:
        result = client.post("/api/v1/auth/register", json={**ACCOUNT, **change}, headers=ORIGIN)
        assert result.status_code == 422
        assert ACCOUNT["password"] not in result.text
        assert client.get("/api/v1/auth/me").status_code == 401


def test_registration_origin_and_disabled_setting(runtime):
    with TestClient(create_app(runtime[0])) as client:
        assert client.post("/api/v1/auth/register", json=ACCOUNT).status_code == 403
        assert (
            client.post(
                "/api/v1/auth/register",
                json=ACCOUNT,
                headers={"Origin": "https://untrusted.invalid"},
            ).status_code
            == 403
        )
        runtime[0].registration_enabled = False
        result = client.post("/api/v1/auth/register", json=ACCOUNT, headers=ORIGIN)
        assert result.status_code == 403 and result.json()["code"] == "REGISTRATION_DISABLED"


def test_duplicate_registration_and_rate_limit_survive_rollback(runtime):
    runtime[0].registration_attempt_limit = 2
    with TestClient(create_app(runtime[0])) as client:
        assert client.post("/api/v1/auth/register", json=ACCOUNT, headers=ORIGIN).status_code == 201
        cookie = client.cookies.get("cheetah_session")
        duplicate = client.post("/api/v1/auth/register", json=ACCOUNT, headers=ORIGIN)
        assert duplicate.status_code == 409 and duplicate.json()["code"] == "USERNAME_TAKEN"
        assert client.cookies.get("cheetah_session") == cookie
        limited = client.post(
            "/api/v1/auth/register", json={**ACCOUNT, "username": "fixture-another"}, headers=ORIGIN
        )
        assert limited.status_code == 429
        assert client.get("/api/v1/auth/me").status_code == 200
        with Session(runtime[1]) as db:
            assert (
                len(
                    list(
                        db.scalars(select(Identity).where(Identity.username == ACCOUNT["username"]))
                    )
                )
                == 1
            )


def test_concurrent_registration_creates_one_identity(runtime):
    def register_once(_):
        with TestClient(create_app(runtime[0])) as client:
            return client.post("/api/v1/auth/register", json=ACCOUNT, headers=ORIGIN).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(register_once, range(2))) == [201, 409]


def test_register_openapi_requires_origin_without_existing_session(runtime):
    operation = create_app(runtime[0]).openapi()["paths"]["/api/v1/auth/register"]["post"]
    assert "security" not in operation
    assert [param["name"] for param in operation["parameters"]] == ["Origin"]
    assert "201" in operation["responses"]


def test_expired_session_blocks_workspace_and_writes(runtime):
    with TestClient(create_app(runtime[0])) as client:
        registered = client.post("/api/v1/auth/register", json=ACCOUNT, headers=ORIGIN)
        session = registered.json()
        with Session(runtime[1]) as db, db.begin():
            login = db.scalar(
                select(LoginSession).where(LoginSession.user_id == session["user"]["id"])
            )
            login.expires_at = utcnow() - timedelta(seconds=1)
        assert client.get("/api/v1/auth/me").status_code == 401
        assert client.get("/api/v1/workspace/summary").status_code == 401
        assert (
            client.post(
                "/api/v1/jobs",
                headers={
                    **ORIGIN,
                    "X-CSRF-Token": session["csrf_token"],
                    "Idempotency-Key": "fixture-expired",
                },
                json={"material_text": "虚构过期请求"},
            ).status_code
            == 401
        )
