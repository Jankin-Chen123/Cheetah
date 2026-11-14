"""Exercise the live protocol path with isolated HTTP fixtures, never a real provider."""

import json

import httpx
from conftest import drain, post, published_job
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Artifact, Budget, ModelUsage, OutboxEvent, SearchUsage
from app.modules.intake.service import validate_handoff


def test_model_and_search_http_protocols_complete_intake_without_mock_parser(
    api, runtime, monkeypatch
):
    settings, engine = runtime
    settings.allow_mock = False
    settings.model_endpoint = "https://model.fixture.invalid/chat/completions"
    settings.model_name = "fixture-model"
    settings.model_api_key = SecretStr("fixture-model-key")
    settings.search_provider = "http_json"
    settings.search_endpoint = "https://search.fixture.invalid/v1/search"
    settings.search_api_key = SecretStr("fixture-search-key")
    settings.search_allowed_domains = ["example.com"]
    original_client = httpx.Client
    calls = []

    def response(request):
        body = json.loads(request.content)
        calls.append((request.url.host, request.headers["Idempotency-Key"]))
        if request.url.host == "model.fixture.invalid":
            assert request.headers["Authorization"] == "Bearer fixture-model-key"
            material = json.loads(body["messages"][1]["content"])["untrusted_material"]
            if "需要工作经验" in material:
                result = {
                    "facts": {
                        "location": {
                            "value": "虚构城市",
                            "status": "stated",
                            "quote": "地点：虚构城市",
                        }
                    },
                    "rules": {},
                }
            else:
                result = {
                    "facts": {
                        "name": {
                            "value": "虚构候选人",
                            "status": "stated",
                            "quote": "姓名：虚构候选人",
                        },
                        "years_experience": {
                            "value": 5,
                            "status": "stated",
                            "quote": "工作年限：5",
                        },
                        "employer": {
                            "value": "FixtureCompany",
                            "status": "stated",
                            "quote": "employer: FixtureCompany",
                        },
                        "employment_period": {
                            "value": "2020-2022",
                            "status": "stated",
                            "quote": "employment_period: 2020-2022",
                        },
                    }
                }
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": json.dumps(result, ensure_ascii=False)}}],
                    "usage": {"total_tokens": 150},
                },
            )
        assert request.url.host == "search.fixture.invalid"
        assert request.headers["Authorization"] == "Bearer fixture-search-key"
        assert "FixtureCompany" in body["query"] and "2020-2022" in body["query"]
        assert "虚构候选人" not in body["query"]
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://example.com/fictional-company",
                        "title": "虚构公司来源",
                        "snippet": "FixtureCompany profile, supplied only by the test transport.",
                        "published_at": "2021-01-01T00:00:00Z",
                    }
                ]
            },
        )

    def client(**kwargs):
        return original_client(transport=httpx.MockTransport(response), **kwargs)

    def forbidden_parser(*args):
        raise AssertionError("The HTTP protocol path must not invoke the mock parser")

    monkeypatch.setattr(httpx, "Client", client)
    monkeypatch.setattr("app.worker.analysis.mock_analysis", forbidden_parser)
    job_id, rule = published_job(
        api, runtime, research_config="bounded-research", execution_mode="live"
    )
    assert not rule["is_test_rule"]
    imported = post(
        api,
        f"/jobs/{job_id}/resume-batches",
        {
            "execution_mode": "live",
            "items": [
                {
                    "client_item_id": "fixture-http-material",
                    "name": "虚构协议测试.txt",
                    "text": (
                        "姓名：虚构候选人\n工作年限：5\nemployer: FixtureCompany\n"
                        "employment_period: 2020-2022"
                    ),
                }
            ],
        },
        expected=202,
    )
    drain(runtime)
    application_id = imported["items"][0]["application_id"]
    application = api.get(f"/api/v1/applications/{application_id}").json()
    assert application["screening_result"] == "passed"
    assert application["provenance"]["source_modes"] == {
        "candidate_material": "manual",
        "model": "live",
        "research": "live",
        "phone": None,
    }
    assert len(calls) == 3 and len({request_id for _, request_id in calls}) == 3
    with Session(engine) as db:
        budget = db.get(Budget, job_id)
        assert (budget.used, budget.reserved, budget.tokens_used, budget.tokens_reserved) == (
            2,
            0,
            300,
            0,
        )
        assert (budget.searches_used, budget.searches_reserved) == (1, 0)
        assert all(record.status == "settled" for record in db.scalars(select(ModelUsage)))
        assert all(record.status == "settled" for record in db.scalars(select(SearchUsage)))
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "screening.passed"))
        payload = validate_handoff(db, event)
        assert payload.source_modes.research == "live" and payload.source_modes.phone is None
        assert not payload.fixture_only
        refs = {kind: ref.model_dump() for kind, ref in payload.artifact_refs.items()}
        assert set(refs) == {f"D{number:02}" for number in range(1, 7)}
        d04 = db.get(Artifact, (refs["D04"]["artifact_id"], refs["D04"]["version"]))
        assert d04.content["status"] == "partial"
        assert d04.content["fields"]["personal_contribution"] == "unknown"
    for ref in refs.values():
        result = api.get(f"/api/v1/artifacts/{ref['artifact_id']}?version={ref['version']}")
        assert result.status_code == 200
        assert all(set(item) == {"kind", "id", "version"} for item in result.json()["input_refs"])
