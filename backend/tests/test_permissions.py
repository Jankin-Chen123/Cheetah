from conftest import drain, post, published_job
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Artifact, Identity, IntakeJob, LoginSession, StoredFile
from app.main import create_app


def test_session_cookie_csrf_logout_and_untrusted_origin(api, runtime):
    assert api.get("/api/v1/auth/me").status_code == 200
    assert api.get("/api/v1/auth/me").headers["Cache-Control"] == "no-store"
    response = api.post("/api/v1/jobs", headers={"X-CSRF-Token": "wrong"}, json={})
    assert response.status_code == 403
    response = api.post("/api/v1/jobs", headers={"Origin": "https://untrusted.example"}, json={})
    assert response.status_code == 403
    assert api.post("/api/v1/auth/logout").status_code == 204
    assert api.get("/api/v1/auth/me").status_code == 401
    with Session(runtime[1]) as db:
        assert not list(db.scalars(select(LoginSession)))
    client = TestClient(create_app(runtime[0]))
    response = client.post(
        "/api/v1/auth/login", json={"username": "fixture-owner", "password": "fixture-password"}
    )
    assert response.status_code == 403
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:5173"},
        json={"username": "fixture-owner", "password": "fixture-password"},
    )
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]


def test_objects_artifacts_evidence_files_tasks_isolated_by_owner_and_org(api, runtime):
    job_id, _ = published_job(api, runtime)
    batch = post(
        api,
        f"/jobs/{job_id}/resume-batches",
        {
            "execution_mode": "mock",
            "items": [{"client_item_id": "one", "name": "虚构.txt", "text": "工作年限：5"}],
        },
        expected=202,
    )
    drain(runtime)
    app_id = batch["items"][0]["application_id"]
    with Session(runtime[1]) as db:
        artifact = db.scalar(
            select(Artifact).where(Artifact.application_id == app_id, Artifact.type == "D03")
        )
        file = db.scalar(select(StoredFile).where(StoredFile.application_id == app_id))
        paths = [
            f"/jobs/{job_id}",
            f"/applications/{app_id}",
            f"/batches/{batch['batch_id']}",
            f"/tasks/{batch['task_id']}",
            f"/artifacts/{artifact.artifact_id}?version=1",
            f"/evidence/{artifact.evidence_refs[0]['evidence_id']}?version=1",
            f"/files/{file.id}?version=1",
        ]
    for username in ("fixture-colleague", "fixture-other"):
        with TestClient(create_app(runtime[0])) as client:
            login = client.post(
                "/api/v1/auth/login",
                headers={"Origin": "http://localhost:5173"},
                json={"username": username, "password": "fixture-password"},
            )
            assert login.status_code == 200
            for path in paths:
                response = client.get("/api/v1" + path)
                assert response.status_code == 404, (path, response.text)
    with TestClient(create_app(runtime[0])) as client:
        for path in paths:
            assert client.get("/api/v1" + path).status_code == 401


def test_idempotency_replay_revalidates_visibility(api, runtime):
    body = {"title": "虚构岗位", "company": "虚构企业", "material_text": "虚构需求"}
    key = "fixture-create-once"
    first = post(api, "/jobs", body, key=key)
    response = api.post("/api/v1/jobs", json=body, headers={"Idempotency-Key": key})
    assert response.status_code == 201 and response.headers["Idempotency-Replayed"] == "true"
    assert response.json() == first
    response = api.post(
        "/api/v1/jobs", json={**body, "title": "不同内容"}, headers={"Idempotency-Key": key}
    )
    assert response.status_code == 409 and response.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    with Session(runtime[1]) as db, db.begin():
        job = db.get(IntakeJob, first["id"])
        colleague = db.scalar(select(Identity).where(Identity.username == "fixture-colleague"))
        job.owner_id = colleague.id
    response = api.post("/api/v1/jobs", json=body, headers={"Idempotency-Key": key})
    assert response.status_code == 404


def test_failed_login_attempts_remain_rate_limited_after_transaction_rollback(api, runtime):
    runtime[0].login_attempt_limit = 3
    for _ in range(2):
        response = api.post(
            "/api/v1/auth/login", json={"username": "fixture-owner", "password": "incorrect"}
        )
        assert response.status_code == 401
    response = api.post(
        "/api/v1/auth/login", json={"username": "fixture-owner", "password": "incorrect"}
    )
    assert response.status_code == 429 and response.json()["code"] == "RATE_LIMITED"
