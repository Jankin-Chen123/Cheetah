import json
from pathlib import Path

from conftest import drain, post, published_job
from jsonschema import Draft202012Validator, FormatChecker

from app.core.config import Settings
from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]


def test_published_design_examples_remain_valid():
    design = json.loads((ROOT / "docs/api/openapi.v1.json").read_text(encoding="utf-8"))
    examples = json.loads((ROOT / "docs/api/examples.json").read_text(encoding="utf-8"))
    for name, case in examples["cases"].items():
        schema = {
            "$ref": f"#/components/schemas/{case['schema']}",
            "components": design["components"],
        }
        errors = list(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(case["value"])
        )
        assert not errors, (name, [error.message for error in errors])


def test_runtime_export_has_security_headers_and_both_import_formats():
    actual = create_app(Settings(_env_file=None, environment="test")).openapi()
    exported = json.loads(
        (ROOT / "docs/api/openapi.implemented.v1.json").read_text(encoding="utf-8")
    )
    assert actual == exported
    operation = actual["paths"]["/api/v1/jobs/{job_id}/resume-batches"]["post"]
    assert set(operation["requestBody"]["content"]) == {"application/json", "multipart/form-data"}
    assert operation["security"] == [{"CookieAuth": []}]
    assert {"Origin", "X-CSRF-Token", "Idempotency-Key"} <= {
        p["name"] for p in operation["parameters"]
    }
    assert "/api/v1/calls" not in actual["paths"]
    design = json.loads((ROOT / "docs/api/openapi.v1.json").read_text(encoding="utf-8"))
    required_routes = {
        ("/api/v1" + path, method)
        for path, methods in design["paths"].items()
        for method, operation in methods.items()
        if isinstance(operation, dict) and operation.get("x-owner") == "A"
    }
    registered_routes = {
        (path, method) for path, methods in actual["paths"].items() for method in methods
    }
    assert required_routes <= registered_routes


def test_created_resource_and_async_location_survive_idempotency_replay(api):
    body = {"title": "虚构岗位", "company": "虚构企业", "material_text": "虚构需求"}
    headers = {"Idempotency-Key": "fixture-location-job"}
    created = api.post("/api/v1/jobs", json=body, headers=headers)
    assert created.status_code == 201
    path = f"/api/v1/jobs/{created.json()['id']}"
    replayed = api.post("/api/v1/jobs", json=body, headers=headers)
    assert replayed.headers["Location"] == created.headers["Location"] == path
    assert replayed.json() == created.json()
    assert api.get(path).status_code == 200

    body = {"expected_revision": created.json()["revision"], "execution_mode": "mock"}
    headers = {"Idempotency-Key": "fixture-location-task"}
    accepted = api.post(path + "/analyze", json=body, headers=headers)
    assert accepted.status_code == 202
    replayed = api.post(path + "/analyze", json=body, headers=headers)
    task_path = f"/api/v1/tasks/{accepted.json()['task_id']}"
    assert replayed.headers["Location"] == accepted.headers["Location"] == task_path
    assert api.get(task_path).status_code == 200


def test_workspace_counts_todos_source_filters_and_safe_draft(api, runtime):
    job_id, _ = published_job(api, runtime)
    received = post(
        api,
        f"/jobs/{job_id}/resume-batches",
        {
            "execution_mode": "mock",
            "items": [{"client_item_id": "one", "name": "虚构.txt", "text": "姓名：虚构候选人"}],
        },
        expected=202,
    )
    drain(runtime)
    summary = api.get("/api/v1/workspace/summary?source_scope=mock").json()
    assert summary["active_job_count"] == 1 and summary["application_count"] == 1
    assert summary["outreach_summary_connected"] is False
    todos = api.get("/api/v1/todos?type=screening_review").json()
    assert (
        todos["total"] == 1
        and todos["items"][0]["application_id"] == received["items"][0]["application_id"]
    )
    assert api.get("/api/v1/applications?source_scope=live").json()["total"] == 0
    job = post(
        api, "/jobs", {"title": "虚构草案", "company": "虚构公司", "material_text": "材料不完整"}
    )
    draft = api.get(f"/api/v1/jobs/{job['id']}/rules/draft")
    assert draft.status_code == 200 and draft.json()["validation_issues"]
    assert api.get("/api/v1/jobs?page_size=1").json()["total"] == 2


def test_stale_draft_revision_and_test_to_live_are_blocked(api, runtime):
    job_id, _ = published_job(api, runtime)
    draft = api.get(f"/api/v1/jobs/{job_id}/rules/draft").json()
    body = {"expected_draft_revision": draft["draft_revision"], "content": draft["content"]}
    assert api.patch(f"/api/v1/jobs/{job_id}/rules/draft", json=body).status_code == 200
    assert api.patch(f"/api/v1/jobs/{job_id}/rules/draft", json=body).status_code == 409
    response = api.post(
        f"/api/v1/jobs/{job_id}/resume-batches",
        headers={"Idempotency-Key": "fixture-live-blocked"},
        json={
            "items": [{"client_item_id": "one", "name": "fiction.txt", "text": "工作年限：5"}],
            "execution_mode": "live",
        },
    )
    assert response.status_code == 409 and response.json()["code"] == "PRECONDITION_NOT_MET"


def test_failed_job_analysis_appears_in_todos_before_any_resume_exists(api, runtime):
    job = post(
        api, "/jobs", {"title": "虚构岗位", "company": "虚构企业", "material_text": "虚构需求"}
    )
    post(
        api,
        f"/jobs/{job['id']}/analyze",
        {"expected_revision": 1, "execution_mode": "live"},
        expected=202,
    )
    drain(runtime)
    response = api.get("/api/v1/todos?type=material_correction")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["job_id"] == job["id"]
