import os
import socket
import subprocess
import sys
import time

import httpx
from conftest import post, published_job
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import OutboxEvent


def test_separate_api_worker_and_api_restart_preserve_completed_artifacts(runtime):
    settings, engine = runtime
    with socket.socket() as socket_probe:
        socket_probe.bind(("127.0.0.1", 0))
        port = socket_probe.getsockname()[1]
    env = dict(os.environ)
    env.update(
        CHEETA_DATABASE_URL=settings.database_url.get_secret_value(),
        CHEETA_ENVIRONMENT="test",
        CHEETA_ALLOW_MOCK="true",
    )
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    def start():
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-access-log",
                "--log-level",
                "warning",
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError("API process exited during startup")
            try:
                if (
                    httpx.get(f"http://127.0.0.1:{port}/api/v1/health", timeout=1).status_code
                    == 200
                ):
                    return process
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        process.terminate()
        process.wait(timeout=10)
        raise AssertionError("API startup timed out")

    process = start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=20) as api:
            session = api.post(
                "/api/v1/auth/login",
                headers={"Origin": "http://localhost:5173"},
                json={"username": "fixture-owner", "password": "fixture-password"},
            )
            assert session.status_code == 200
            api.headers.update(
                {"Origin": "http://localhost:5173", "X-CSRF-Token": session.json()["csrf_token"]}
            )
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
            completed = subprocess.run(
                [sys.executable, "-m", "app.worker", "--drain"],
                env=env,
                capture_output=True,
                timeout=30,
                creationflags=flags,
            )
            assert completed.returncode == 0, "Separate worker did not complete"
            app_id = batch["items"][0]["application_id"]
            before = api.get(f"/api/v1/applications/{app_id}").json()
            assert before["screening_result"] == "passed"
            process.terminate()
            process.wait(timeout=10)
            process = start()
            assert api.get("/api/v1/auth/me").status_code == 200
            after = api.get(f"/api/v1/applications/{app_id}").json()
            assert after["artifact_slots"] == before["artifact_slots"]
            assert after["screening_result"] == "passed"
            assert after["provenance"]["fixture_only"]
        with Session(engine) as db:
            events = list(
                db.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "screening.passed"))
            )
            assert len(events) == 1 and events[0].status == "pending"
    finally:
        process.terminate()
        process.wait(timeout=10)
