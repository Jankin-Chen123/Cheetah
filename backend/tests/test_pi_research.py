"""Run the actual installed Pi loop through fixture HTTP, including adaptive follow-up research."""

import copy
import json

import httpx
import pytest
from conftest import drain, post, published_job
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Artifact, Budget, ResearchRun, Task
from app.integrations.search import SearchResult
from app.modules.intake.a03_contracts import ObjectFindings
from app.modules.intake.a03_state import checked_findings


def fact(value, quote=None):
    return {"value": value, "status": "stated", "quote": quote or str(value)}


OBJECTS = [
    {
        "object_id": "company_a",
        "kind": "company",
        "name": fact("FixtureCompany"),
        "period": fact("2020-2022"),
        "parent_object_id": None,
        "facts": {
            "location": fact("FixtureCity"),
            "products": fact("DataPlatform"),
            "description": fact("DataPlatform business"),
            "contribution": fact("team revenue 50"),
        },
    },
    {
        "object_id": "project_a",
        "kind": "project",
        "name": fact("FixtureProject"),
        "period": fact("2021"),
        "parent_object_id": "company_a",
        "facts": {"company": fact("FixtureCompany"), "contribution": fact("team revenue 50")},
    },
    {
        "object_id": "paper_a",
        "kind": "paper",
        "name": fact("FixturePaper"),
        "period": fact("2022"),
        "parent_object_id": None,
        "facts": {"status": fact("preprint"), "identifier": fact("10.1234/fixture")},
    },
]
MATERIAL = "\n".join(
    [
        "姓名：虚构人",
        "工作年限：5",
        *[
            str(value["value"])
            for item in OBJECTS
            for value in [item["name"], item["period"], *item["facts"].values()]
        ],
    ]
)
PAGE = "FixtureCompany FixtureCity DataPlatform business. 2021. Historical context 2020-2022."


def setup_agent(api, runtime, monkeypatch, *, max_turns=16):
    job_id, _ = published_job(api, runtime, research_config="pi-research")
    settings = runtime[0]
    settings.model_endpoint = "https://model.fixture.invalid/chat"
    settings.model_api_key = SecretStr("fixture-key")
    settings.model_name = "fixture-tools-model"
    settings.a03_web_backend = "normalized"
    settings.search_provider = "fixture"
    settings.search_allowed_domains = ["example.com"]
    settings.a03_fetch_endpoint = "https://pages.fixture.invalid/read"
    settings.a03_max_turns = max_turns
    original = __import__("app.modules.intake.analysis", fromlist=["mock_analysis"]).mock_analysis

    def extract(kind, material):
        result = original(kind, material)
        if kind == "resume_parse":
            result["research_objects"] = copy.deepcopy(OBJECTS)
        return result

    monkeypatch.setattr("app.worker.analysis.mock_analysis", extract)

    class SearchFixture:
        source_mode = "mock"

        def __init__(self):
            self.calls = []

        def search(self, query, *, request_id):
            self.calls.append((query, request_id))
            number = len(self.calls)
            return SearchResult.model_validate(
                {
                    "results": [
                        {
                            "url": f"https://example.com/company-{number}",
                            "title": "虚构来源",
                            "snippet": "同名公司，需继续核对地区" if number == 1 else PAGE,
                        }
                    ]
                }
            )

    adapter = SearchFixture()
    monkeypatch.setattr("app.modules.intake.a03_runtime.get_search_adapter", lambda _: adapter)
    imported = post(
        api,
        f"/jobs/{job_id}/resume-batches",
        {
            "execution_mode": "mock",
            "items": [{"client_item_id": "one", "name": "fixture.txt", "text": MATERIAL}],
        },
        expected=202,
    )
    return job_id, imported["items"][0]["application_id"], adapter


def install_model(monkeypatch, decide):
    original = httpx.Client
    requests = []

    def respond(request):
        body = json.loads(request.content)
        if request.url.host == "pages.fixture.invalid":
            return httpx.Response(
                200, json={"url": body["url"], "text": PAGE, "source_date": "2021"}
            )
        assert request.url.host == "model.fixture.invalid"
        number = len(requests)
        requests.append(body)
        name, args = decide(number, body)
        assert {tool["function"]["name"] for tool in body["tools"]} == {
            "load_skill",
            "set_research_plan",
            "search_public_sources",
            "read_public_source",
            "record_object_findings",
            "finish_research",
        }
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": f"fixture-call-{number}",
                                    "type": "function",
                                    "function": {
                                        "name": name,
                                        "arguments": json.dumps(args, ensure_ascii=False),
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"total_tokens": 100},
            },
        )

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs)
    )
    return requests


def plan():
    return {
        "goals": [
            {
                "object_id": "company_a",
                "field": "industry",
                "question": "核实业务背景",
                "priority": "high",
                "rationale": "岗位相关的核心经历",
            }
        ]
    }


def last_result(body):
    return json.loads(next(m["content"] for m in reversed(body["messages"]) if m["role"] == "tool"))


def findings(source_id):
    citation = {"source_id": source_id, "quote": PAGE, "source_date": "2021"}
    return {
        "object_id": "company_a",
        "identity": {
            "status": "confirmed",
            "rationale": "原名与地区、产品一致",
            "citations": [citation],
            "a04_anchor_fields": ["location", "products"],
        },
        "findings": [
            {
                "field": "industry",
                "category": "E1",
                "text": "DataPlatform business",
                "citations": [citation],
                "applicable_period": "2020-2022",
                "historical_applicability": "confirmed",
            },
            {
                "field": "contribution",
                "category": "E1",
                "text": "候选人贡献尚待本人核实。",
                "citations": [citation],
            },
        ],
        "gaps": ["候选人个人贡献尚未获得独立依据"],
        "verification_questions": ["请说明本人负责模块与结果归因"],
        "stop_reason": "sufficient",
    }


def test_actual_pi_loop_observes_results_refines_query_and_delivers_five_section_report(
    api, runtime, monkeypatch
):
    job_id, app_id, adapter = setup_agent(api, runtime, monkeypatch)
    source_ids = []

    def decide(number, body):
        if number == 0:
            return "load_skill", {"name": "evidence-quality"}
        if number == 1:
            return "set_research_plan", plan()
        if number in {2, 4}:
            if number == 4:
                assert "source" in last_result(body)
            return "search_public_sources", {
                "object_id": "company_a",
                "query": "FixtureCompany" + (" FixtureCity 2021" if number == 4 else " official"),
                "purpose": "同名消歧" if number == 4 else "查找官方来源",
            }
        if number in {3, 5}:
            source_id = last_result(body)["sources"][0]["source_id"]
            source_ids.append(source_id)
            return "read_public_source", {"object_id": "company_a", "source_id": source_id}
        if number == 6:
            return "record_object_findings", findings(source_ids[-1])
        if number == 7:
            assert last_result(body)["findings"][1]["category"] == "U"
            return "load_skill", {"name": "report-handoff"}
        return "finish_research", {
            "reason": "sufficient",
            "summary": "公司背景已取得来源，其他对象和个人贡献保留待核实。",
        }

    requests = install_model(monkeypatch, decide)
    drain(runtime)
    assert len(requests) == 9 and len(adapter.calls) == 2
    assert "FixtureCity" in adapter.calls[1][0]
    with Session(runtime[1]) as db:
        d03 = db.scalar(
            select(Artifact).where(Artifact.type == "D03", Artifact.application_id == app_id)
        )
        assert len(d03.content["research_objects"]) == 3
        assert len(d03.content["employment"]) == 1 and len(d03.content["projects"]) == 1
        assert d03.content["research_objects"][0]["facts"]["location"]["evidence_refs"]
        d04 = db.scalar(
            select(Artifact).where(Artifact.type == "D04", Artifact.application_id == app_id)
        )
        assert d04 is not None
        report = d04.content["report"]
        assert report["status"] == "partial"
        assert report["candidate_id"] != app_id
        assert len(report["objects"]) == 3
        company = report["objects"][0]
        industry = next(field for field in company["fields"] if field["field"] == "industry")
        assert industry["public_information"][0]["category"] == "E1"
        contribution = next(
            field for field in company["fields"] if field["field"] == "contribution"
        )
        assert contribution["public_information"][0]["category"] == "U"
        assert all(item["state"] == "not_executed" for item in report["objects"][1:])
        assert (
            report["objects"][2]["original_information"]["facts"]["status"]["value"] == "preprint"
        )
        assert report["execution"]["runtime"] == "pi-agent-core"
        assert report["execution"]["fixture_only"]
        assert report["execution"]["searches"] == 2 and report["execution"]["pages"] == 2
        budget = db.get(Budget, job_id)
        assert budget.searches_used == 2 and budget.searches_reserved == 0
        assert budget.used == 9 and budget.reserved == 0
        assert db.scalar(select(ResearchRun)).messages
        path = f"/api/v1/artifacts/{d04.artifact_id}?version=1"
    markdown = api.get(path).json()["content_markdown"]
    assert all(
        section in markdown
        for section in ["一、任务", "二、任职", "三、项目", "四、比赛", "五、研究"]
    )
    assert "FixturePaper" in markdown and "https://example.com/company-2" in markdown


def test_actual_pi_turn_cap_preserves_all_unresearched_objects(api, runtime, monkeypatch):
    _, app_id, adapter = setup_agent(api, runtime, monkeypatch, max_turns=2)
    requests = install_model(monkeypatch, lambda number, body: ("set_research_plan", plan()))
    drain(runtime)
    assert len(requests) == 2 and not adapter.calls
    with Session(runtime[1]) as db:
        report = db.scalar(
            select(Artifact).where(Artifact.type == "D04", Artifact.application_id == app_id)
        ).content["report"]
        assert report["stop_reason"] == "a03_turn_limit"
        assert len(report["objects"]) == 3
        assert report["execution"]["model_turns"] == 2


def test_actual_pi_unknown_search_outcome_is_not_resubmitted(api, runtime, monkeypatch):
    _, app_id, adapter = setup_agent(api, runtime, monkeypatch)

    def timeout(*args, **kwargs):
        adapter.calls.append(("timeout", "fixture"))
        raise httpx.ReadTimeout("fixture unknown outcome")

    adapter.search = timeout
    install_model(
        monkeypatch,
        lambda number, body: (
            ("set_research_plan", plan())
            if number == 0
            else (
                "search_public_sources",
                {"object_id": "company_a", "query": "FixtureCompany official", "purpose": "核对"},
            )
        ),
    )
    drain(runtime)
    with Session(runtime[1]) as db:
        task = db.scalar(select(Task).where(Task.kind == "research", Task.application_id == app_id))
        assert task.status == "reconciling" and task.error_code == "EXTERNAL_RESULT_UNKNOWN"
        assert not db.scalar(
            select(Artifact).where(Artifact.type == "D04", Artifact.application_id == app_id)
        )
        assert db.get(Budget, task.job_id).searches_reserved == 1
    drain(runtime)
    assert len(adapter.calls) == 1


def test_pi_restart_replays_saved_tool_result_without_repeating_external_query(
    api, runtime, monkeypatch
):
    from app.modules.intake.a03_runtime import ResearchHost

    _, app_id, adapter = setup_agent(api, runtime, monkeypatch)
    install_model(
        monkeypatch,
        lambda number, body: (
            ("set_research_plan", plan())
            if number == 0
            else (
                "search_public_sources",
                {
                    "object_id": "company_a",
                    "query": "FixtureCompany official",
                    "purpose": "核对主体",
                },
            )
            if number == 1
            else (
                "finish_research",
                {"reason": "identity_uncertain", "summary": "公开线索不足，保留未知"},
            )
        ),
    )
    original = ResearchHost.dispatch
    interrupted = []

    def crash_after_tool_result(self, method, args):
        messages = args.get("messages", [])
        if (
            method == "checkpoint"
            and messages
            and messages[-1].get("role") == "toolResult"
            and messages[-1].get("toolName") == "search_public_sources"
            and not interrupted
        ):
            interrupted.append(True)
            raise RuntimeError("fixture crash after known search receipt")
        return original(self, method, args)

    monkeypatch.setattr(ResearchHost, "dispatch", crash_after_tool_result)
    drain(runtime)
    with Session(runtime[1]) as db:
        task = db.scalar(select(Task).where(Task.kind == "research", Task.application_id == app_id))
        assert task.status == "failed" and task.external_state == "settled"
        task_id, revision = task.id, task.revision
    assert len(adapter.calls) == 1
    post(
        api,
        f"/tasks/{task_id}/retry",
        {"expected_revision": revision, "reason": "恢复内部状态"},
        expected=202,
    )
    drain(runtime)
    assert len(adapter.calls) == 1
    with Session(runtime[1]) as db:
        assert db.get(Task, task_id).status == "completed"
        assert db.get(Budget, task.job_id).searches_used == 1


def test_object_fact_correction_preserves_other_objects_and_invalidates_old_research(
    api, runtime, monkeypatch
):
    _, app_id, _ = setup_agent(api, runtime, monkeypatch)
    install_model(
        monkeypatch,
        lambda number, body: (
            ("set_research_plan", plan())
            if number == 0
            else ("finish_research", {"reason": "no_sources", "summary": "没有来源，保留未知"})
        ),
    )
    drain(runtime)
    with Session(runtime[1]) as db:
        profile = db.scalar(
            select(Artifact).where(Artifact.type == "D03", Artifact.application_id == app_id)
        )
        ref = {"artifact_id": profile.artifact_id, "version": profile.version}
    response = post(
        api,
        f"/applications/{app_id}/corrections",
        {
            "target_artifact_ref": ref,
            "changes": [
                {
                    "path": "/research_objects/company_a/facts/location",
                    "value": fact("CorrectedCity", "人工核对地区 CorrectedCity"),
                    "reason": "更正地区",
                }
            ],
            "evidence_refs": [],
            "reason": "核实后更正公司消歧线索",
        },
    )
    new_ref = response["new_artifact_ref"]
    profile = api.get(
        f"/api/v1/artifacts/{new_ref['artifact_id']}?version={new_ref['version']}"
    ).json()
    objects = profile["structured_content"]["research_objects"]
    assert objects[0]["facts"]["location"]["value"] == "CorrectedCity"
    assert objects[0]["facts"]["location"]["source_type"] == "manual_revision"
    assert objects[2]["name"]["value"] == "FixturePaper"
    assert len(response["invalidated_artifact_refs"]) == 4


def test_pi_disabled_provider_delivers_all_objects_without_claiming_execution(
    api, runtime, monkeypatch
):
    _, app_id, adapter = setup_agent(api, runtime, monkeypatch)
    runtime[0].a03_web_backend = "disabled"
    requests = install_model(
        monkeypatch, lambda *_: pytest.fail("No provider means no agent calls")
    )
    drain(runtime)
    assert not requests and not adapter.calls
    with Session(runtime[1]) as db:
        report = db.scalar(
            select(Artifact).where(Artifact.type == "D04", Artifact.application_id == app_id)
        ).content["report"]
        assert report["status"] == "not_executed" and len(report["objects"]) == 3
        assert report["execution"]["runtime"] is None


def test_search_guard_rejects_contacts_and_new_subject_before_any_external_request(
    api, runtime, monkeypatch
):
    _, _, adapter = setup_agent(api, runtime, monkeypatch, max_turns=4)

    def decide(number, body):
        if number == 0:
            return "set_research_plan", plan()
        if number in {1, 2}:
            return "search_public_sources", {
                "object_id": "company_a" if number == 1 else "invented_company",
                "query": "FixtureCompany person@example.invalid",
                "purpose": "不应发送",
            }
        assert last_result(body)["error"] == "VALIDATION_ERROR"
        return "finish_research", {"reason": "no_sources", "summary": "查询被边界拒绝，保留未知"}

    install_model(monkeypatch, decide)
    drain(runtime)
    assert not adapter.calls


@pytest.mark.parametrize("fault", ["snippet", "quote", "date", "identity"])
def test_evidence_guard_downgrades_unsupported_public_assertions(fault):
    source_id = "fixture-source"
    state = {
        "objects": copy.deepcopy(OBJECTS),
        "sources": {
            source_id: {
                "object_id": "company_a",
                "kind": "page",
                "text": PAGE,
            }
        },
    }
    data = findings(source_id)
    if fault == "snippet":
        state["sources"][source_id]["kind"] = "snippet"
    elif fault == "quote":
        data["findings"][0]["citations"][0]["quote"] = "not in the source"
    elif fault == "date":
        data["findings"][0]["citations"][0]["source_date"] = "1999"
    else:
        data["identity"]["a04_anchor_fields"] = []
    checked = checked_findings(state, ObjectFindings.model_validate(data))
    assert checked["findings"][0]["category"] == "U"
    assert checked["findings"][0]["validation_notes"]


def test_personal_contribution_requires_direct_quote_and_independent_identity_anchor():
    source_id = "fixture-source"
    objects = copy.deepcopy(OBJECTS)
    objects[0]["facts"]["orcid"] = fact("0000-0000-0000-0001")
    personal = "FixturePerson 0000-0000-0000-0001 delivered DataPlatform module."
    state = {
        "objects": objects,
        "private_name": "FixturePerson",
        "sources": {
            source_id: {
                "object_id": "company_a",
                "kind": "page",
                "text": PAGE + " " + personal,
            }
        },
    }
    data = findings(source_id)
    data["findings"][1].update(
        text=personal,
        personal_identity_fields=["orcid"],
        citations=[
            {
                "source_id": source_id,
                "quote": PAGE + " " + personal,
                "source_date": "2021",
            }
        ],
    )
    checked = checked_findings(state, ObjectFindings.model_validate(data))
    assert checked["findings"][1]["category"] == "E1"
    state["private_name"] = "DifferentPerson"
    checked = checked_findings(state, ObjectFindings.model_validate(data))
    assert checked["findings"][1]["category"] == "U"
