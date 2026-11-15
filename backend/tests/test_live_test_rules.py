import json
from uuid import uuid4

import httpx
import pytest
from conftest import drain, post, published_job
from intake_fixtures import RESUME_TEXT, assessment_output, resume_output
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Artifact, OutboxEvent
from app.modules.intake import analysis


@pytest.mark.parametrize("enabled", [True, False])
def test_real_model_can_use_opted_in_test_rule_without_upgrading_test_provenance(
    api, runtime, monkeypatch, enabled
):
    job_id, _ = published_job(api, runtime)
    job = api.get("/api/v1/jobs/" + job_id).json()
    assert (
        api.patch(
            "/api/v1/jobs/" + job_id,
            json={"expected_revision": job["revision"], "routing_directions": ["backend"]},
        ).status_code
        == 200
    )
    settings, _ = runtime
    settings.model_endpoint = "https://fixture.invalid/chat"
    settings.model_name = "fixture"
    settings.model_api_key = SecretStr("fixture-key")
    original = httpx.Client
    calls = []

    def respond(request):
        calls.append(request)
        body = json.loads(request.content)
        context = json.loads(body["messages"][-1]["content"])["untrusted_material"]
        output = (
            assessment_output(json.loads(context))
            if len(calls) > 1
            else {
                **resume_output(),
                "direction_assignments": [
                    {
                        "direction_id": "backend",
                        "level": "primary",
                        "quote": "负责企业软件后端服务设计及项目交付",
                        "reason": "本人职责",
                    }
                ],
            }
        )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(output)}}],
                "usage": {"total_tokens": 100},
            },
        )

    monkeypatch.setattr(
        analysis.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    receipt = post(
        api,
        "/talent-imports",
        {
            "execution_mode": "live",
            "items": [{"client_item_id": "one", "name": "fiction.txt", "text": RESUME_TEXT}],
        },
        expected=202,
    )["items"][0]
    drain(runtime)
    person = api.get("/api/v1/talents/" + receipt["talent_id"]).json()
    assert len(person["applications"]) == 1
    application = api.get(
        "/api/v1/applications/" + person["applications"][0]["application_id"]
    ).json()
    settings.allow_mock = enabled
    response = api.post(
        "/api/v1/applications/" + application["id"] + "/start-screening",
        json={
            "expected_revision": application["revision"],
            "reason": "只在隔离内测启用真实模型，保持测试来源",
        },
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert response.status_code == (202 if enabled else 403)
    if not enabled:
        return
    drain(runtime)
    with Session(runtime[1]) as db:
        d03 = db.scalar(select(Artifact).where(Artifact.type == "D03"))
        assert d03.source_mode == "live"
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "screening.passed"))
        assert event is not None
        assert event.payload["fixture_only"] and event.payload["phone_execution_mode"] == "mock"
        assert event.payload["source_modes"]["phone"] is None
    assert len(calls) == 1  # Published fixture uses the deterministic predicate screener.
