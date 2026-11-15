import json
from uuid import uuid4

import httpx
import pytest
from conftest import drain, post
from intake_fixtures import RESUME_TEXT, resume_output
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Budget, Task
from app.modules.intake import analysis


def fail_talent(api, runtime, monkeypatch):
    settings, _ = runtime
    settings.model_endpoint = "https://fixture.invalid/chat"
    settings.model_name = "fixture-model"
    from pydantic import SecretStr

    settings.model_api_key = SecretStr("fixture-key")
    received = post(
        api,
        "/talent-imports",
        {
            "execution_mode": "live",
            "items": [{"client_item_id": "one", "name": "fiction.txt", "text": RESUME_TEXT}],
        },
        expected=202,
    )["items"][0]
    calls = []
    original = httpx.Client

    def respond(request):
        calls.append(json.loads(request.content))
        output = {**resume_output(), "direction_assignments": []}
        content = "" if len(calls) == 1 else json.dumps(output)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length" if len(calls) == 1 else "stop",
                        "message": {"content": content},
                    }
                ],
                "usage": {"total_tokens": 500},
            },
        )

    monkeypatch.setattr(
        analysis.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    drain(runtime)
    return received, calls


def test_explicit_known_failure_regeneration_is_bounded_owned_and_idempotent(
    api, runtime, monkeypatch
):
    received, calls = fail_talent(api, runtime, monkeypatch)
    with Session(runtime[1]) as db, db.begin():
        failed = db.get(Task, received["task_id"])
        failed.payload = {**failed.payload, "agent_resource_hash": "previous-release"}
    task = api.get("/api/v1/tasks/" + received["task_id"]).json()
    assert task["status"] == "failed" and "regenerate" in task["allowed_actions"]
    key = uuid4().hex
    body = {"expected_revision": task["revision"], "reason": "显式恢复已确认的输出失败"}
    first = post(api, f"/tasks/{task['id']}/regenerate", body, key=key, expected=202)
    replay = post(api, f"/tasks/{task['id']}/regenerate", body, key=key, expected=202)
    assert first == replay and first["task_id"] != task["id"]
    drain(runtime)
    assert len(calls) == 2
    assert "上一轮返回结构无效" in calls[-1]["messages"][0]["content"]
    assert api.get("/api/v1/talents/" + received["talent_id"]).json()["profile_version"] == 1
    with Session(runtime[1]) as db:
        assert db.get(Task, task["id"]).status == "failed"
        assert db.get(Task, task["id"]).payload["regenerated_task_id"] == first["task_id"]
        assert db.get(Budget, "talent:" + received["talent_id"]).used == 2
        regenerated = db.get(Task, first["task_id"])
        assert regenerated.payload["regeneration_previous_resource_hash"] == "previous-release"
        assert regenerated.payload["agent_resource_hash"] != "previous-release"
    assert "retry" not in api.get("/api/v1/tasks/" + task["id"]).json()["allowed_actions"]
    assert (
        api.post(
            "/api/v1/tasks/" + first["task_id"] + "/regenerate",
            json={"expected_revision": 1, "reason": "不能反复调用"},
            headers={"Idempotency-Key": uuid4().hex},
        ).status_code
        == 409
    )


@pytest.mark.parametrize("state", ["reconciling", "running", "queued"])
def test_unknown_or_active_outcome_cannot_regenerate(api, runtime, monkeypatch, state):
    received, calls = fail_talent(api, runtime, monkeypatch)
    with Session(runtime[1]) as db, db.begin():
        task = db.get(Task, received["task_id"])
        task.status = state
        task.external_state = "unknown"
        revision = task.revision
    response = api.post(
        "/api/v1/tasks/" + received["task_id"] + "/regenerate",
        json={"expected_revision": revision, "reason": "外部结果不明必须阻止"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert response.status_code == 409 and len(calls) == 1
    with Session(runtime[1]) as db:
        assert len(list(db.scalars(select(Task)))) == 1


def test_other_owner_cannot_regenerate_even_with_known_task_id(api, runtime, monkeypatch):
    received, calls = fail_talent(api, runtime, monkeypatch)
    login = api.post(
        "/api/v1/auth/login", json={"username": "fixture-other", "password": "fixture-password"}
    )
    api.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    response = api.post(
        "/api/v1/tasks/" + received["task_id"] + "/regenerate",
        json={"expected_revision": 1, "reason": "不得访问其他账号任务"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert response.status_code == 404 and len(calls) == 1


def test_failed_interview_child_regenerates_in_same_job_and_completes_parent(
    api, runtime, monkeypatch
):
    from intake_fixtures import JOB_TEXT, interview_output, job_output, rubric_output
    from pydantic import SecretStr

    settings, _ = runtime
    settings.model_endpoint = "https://fixture.invalid/chat"
    settings.model_name = "fixture"
    settings.model_api_key = SecretStr("fixture-key")
    original = httpx.Client
    calls = []
    outputs = [job_output(), {}, interview_output(), {"rubric": rubric_output()}]

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(outputs[len(calls) - 1])}}],
                "usage": {"total_tokens": 100},
            },
        )

    monkeypatch.setattr(
        analysis.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    job = post(api, "/jobs", {"material_text": JOB_TEXT})
    parent = post(
        api,
        f"/jobs/{job['id']}/analyze",
        {"expected_revision": job["revision"], "execution_mode": "live"},
        expected=202,
    )
    drain(runtime)
    parent_task = api.get("/api/v1/tasks/" + parent["task_id"]).json()
    assert parent_task["status"] == "failed"
    child = api.get("/api/v1/tasks/" + parent_task["continuation_task_id"]).json()
    assert child["kind"] == "interview_standard" and child["status"] == "failed"
    replacement = post(
        api,
        f"/tasks/{child['id']}/regenerate",
        {"expected_revision": child["revision"], "reason": "修复已知输出后继续原岗位任务链"},
        expected=202,
    )
    drain(runtime)
    assert len(calls) == 4
    final_job = api.get("/api/v1/jobs/" + job["id"]).json()
    assert final_job["d01_ref"] and final_job["d02_ref"] and not final_job["active_task_ids"]
    with Session(runtime[1]) as db:
        states = [(t.kind, t.status, t.error_code) for t in db.scalars(select(Task))]
    assert api.get("/api/v1/tasks/" + parent["task_id"]).json()["status"] == "completed", states
    assert api.get("/api/v1/tasks/" + child["id"]).json()["status"] == "failed"
    assert api.get("/api/v1/tasks/" + replacement["task_id"]).json()["status"] == "completed"
