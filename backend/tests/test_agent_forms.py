import hashlib
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from conftest import drain, post
from intake_fixtures import (
    JOB_TEXT,
    RESUME_TEXT,
    assessment_output,
    interview_output,
    job_output,
    resume_output,
    rubric_output,
)
from pydantic import SecretStr, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.artifacts import artifact_ref, artifact_view, latest
from app.core.models import Application, Artifact, IntakeJob, ModelUsage, OutboxEvent, Task
from app.modules.intake.agent_prompts import AGENTS, source_prompt, system_prompt
from app.modules.intake.analysis import parse_file
from app.modules.intake.evidence_screening import compute_scores, validate_assessment
from app.modules.intake.form_contracts import (
    JobForm,
    ResumeForm,
    ScreeningAssessment,
    ScreeningRubric,
)
from app.modules.intake.form_sources import check_form_sources, resume_objects
from app.modules.intake.salary import salary_score
from app.modules.intake.schemas import JobAnalysis, ResumeProfile
from app.modules.intake.service import validate_handoff
from app.worker import run_once


def test_supplied_sources_are_pinned_and_role_specific():
    root = Path(__file__).resolve().parents[2] / "docs/简历初筛Agent开发资料"
    for kind, code in AGENTS.items():
        source = next(root.glob(code + "*.md")).read_text(encoding="utf-8-sig")
        assert source_prompt(code) == source
        assert source in system_prompt(kind, JobAnalysis if code == "A01" else ResumeProfile)
        manifest = json.loads(
            (
                Path(__file__).resolve().parents[1] / "agents/intake/resources/manifest.json"
            ).read_text(encoding="utf-8")
        )
        template = root / manifest[code]["template"]["source"]
        assert (
            hashlib.sha256(template.read_bytes()).hexdigest()
            == manifest[code]["template"]["sha256"]
        )


def test_forms_require_all_modules_and_preserve_all_research_objects():
    form = ResumeForm.model_validate(resume_output()["resume_form"])
    checked = check_form_sources(form, RESUME_TEXT)
    objects = resume_objects(checked)
    assert len(objects) == 10
    assert len([o for o in objects if o["kind"] == "company"]) == 2
    assert {o["kind"] for o in objects} == {
        "company",
        "project",
        "award",
        "paper",
        "patent",
        "software_copyright",
        "open_source",
        "certification",
    }
    assert objects[2]["parent_object_id"] == "company_1"
    assert objects[2]["facts"]["outcomes"]["value"] == "团队完成迁移"
    assert not any("电话" in str(o) or "邮箱" in str(o) for o in objects)
    incomplete = resume_output()["resume_form"]
    del incomplete["sections"]["教育经历"]
    with pytest.raises(ValidationError):
        ResumeForm.model_validate(incomplete)
    job = job_output()["job_form"]
    assert len(job["fields"]) == 38
    del job["fields"]["用人部门"]
    with pytest.raises(ValidationError):
        JobForm.model_validate(job)


def test_fabricated_form_fact_is_downgraded_without_changing_source_material():
    original = RESUME_TEXT
    form = ResumeForm.model_validate(resume_output()["resume_form"])
    form.sections["基本信息"][0].fields["当前岗位"].value = "研发总监"
    checked = check_form_sources(form, RESUME_TEXT)
    assert checked.sections["基本信息"][0].fields["当前岗位"].status == "unknown"
    assert checked.parse_status == "partial" and RESUME_TEXT == original


def test_numeric_substrings_cannot_shrink_money_or_years():
    from app.modules.intake.form_contracts import SourceFact

    form = JobForm.model_validate(job_output()["job_form"])
    form.fields["转正薪资"] = SourceFact(value="5万元", quote="预算15万元", status="stated")
    checked = check_form_sources(form, JOB_TEXT + "\n预算15万元")
    assert checked.fields["转正薪资"].status == "unknown"


@pytest.mark.parametrize("extra,expected", [(0, 9), (5, 8), (15, 7), (30, 6), (50, 4), (51, 2)])
def test_salary_boundaries_are_deterministic(extra, expected):
    budget = "预算税前固定年薪100万元/年"
    assert salary_score(budget, f"期望税前固定年薪{100 + extra}万元/年") == expected
    assert salary_score(budget, "薪资面议") is None
    assert salary_score(budget, "期望税后固定年薪100万元/年") is None
    assert salary_score("税前固定月薪10000元/月", "税前固定年薪120000元/年") == 9


def test_unknown_score_does_not_become_zero_or_redistribute_weight():
    rubric = ScreeningRubric.model_validate(rubric_output())
    assessment = ScreeningAssessment.model_validate(
        assessment_output(
            {"allowed_evidence": [{"category": "E2", "evidence_id": "fixture", "version": 1}]}
        )
    )
    scores = {s.dimension_id: s for s in assessment.scores}
    summary = compute_scores(rubric, scores)
    assert summary["coverage"] == 95 and summary["contribution"] == 76
    assert summary["total"] is None
    scores["salary"].score = 8
    assert compute_scores(rubric, scores)["total"] == 80
    broken = rubric_output()
    broken["dimensions"][0]["weight"] = 30
    with pytest.raises(ValidationError):
        ScreeningRubric.model_validate(broken)


def test_forged_and_relabelled_evidence_cannot_support_a_score():
    rubric = ScreeningRubric.model_validate(rubric_output())
    assessment = ScreeningAssessment.model_validate(
        assessment_output(
            {"allowed_evidence": [{"category": "E2", "evidence_id": "fixture", "version": 1}]}
        )
    )
    with pytest.raises(ValueError, match="Unknown, stale"):
        validate_assessment(assessment, rubric, {})
    with pytest.raises(ValueError, match="relabelled"):
        validate_assessment(assessment, rubric, {("fixture", 1): {"category": "E1"}})


def test_legacy_manual_unknowns_remain_unknown_even_when_a_quote_exists():
    from types import SimpleNamespace

    from app.modules.intake.evidence_screening import allowed_evidence

    ref = {"evidence_id": "fixture", "version": 1}
    item = SimpleNamespace(
        evidence_id="fixture",
        version=1,
        status="valid",
        application_id="app",
        organization_id="org",
        category=None,
        source_type="manual_revision",
        quote="需要进一步核实",
        location={},
        public_url=None,
        source_date=None,
    )
    db = SimpleNamespace(get=lambda *args: item)
    application = SimpleNamespace(id="app", organization_id="org")
    d03 = SimpleNamespace(
        content={"facts": {"skills": {"value": None, "status": "unknown", "evidence_refs": [ref]}}},
        evidence_refs=[ref],
    )
    d04 = SimpleNamespace(evidence_refs=[])
    assert allowed_evidence(db, application, d03, d04)[("fixture", 1)]["category"] == "U"


def test_docx_tables_are_read_and_images_are_marked_unreadable(runtime):
    data = BytesIO()
    with ZipFile(data, "w") as z:
        z.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:tbl><w:tr><w:tc><w:p><w:r><w:t>虚构表格简历</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>',
        )
        z.writestr("word/media/fixture.png", b"fictional-unreadable-image")
    text = parse_file("fixture.docx", "application/octet-stream", data.getvalue(), runtime[0])
    assert "虚构表格简历" in text and "[[UNREADABLE_EMBEDDED_CONTENT]]" in text


def setup_model(runtime, monkeypatch, assessment_transform=None):
    settings, _ = runtime
    settings.model_endpoint = "https://fixture.invalid/chat"
    settings.model_name = "fixture"
    settings.model_api_key = SecretStr("fixture-only")
    calls = []

    def invoke(settings, kind, text, request_id):
        calls.append(kind)
        outputs = {
            "job_analysis": job_output,
            "interview_standard": interview_output,
            "screening_standard": lambda: {"rubric": rubric_output()},
            "resume_parse": resume_output,
        }
        if kind == "screening":
            output = assessment_output(json.loads(text))
            if assessment_transform:
                assessment_transform(output)
        else:
            output = outputs[kind]()
        return output, 100

    monkeypatch.setattr("app.worker.analysis.invoke_model", invoke)
    return calls


def publish_material_job(api, runtime):
    job = post(
        api, "/jobs", {"title": "后端工程师", "company": "虚构研究公司", "material_text": JOB_TEXT}
    )
    accepted = post(
        api,
        f"/jobs/{job['id']}/analyze",
        {"expected_revision": job["revision"], "execution_mode": "live"},
        expected=202,
    )
    drain(runtime)
    job = api.get(f"/api/v1/jobs/{job['id']}").json()
    draft = api.get(f"/api/v1/jobs/{job['id']}/rules/draft").json()
    content = draft["content"]
    assert content["screening_rubric"] and len(content["interview_dimensions"]) == 3
    # A/B recommendation configuration is separately reviewed, not invented by A01/A02.
    content["recommendation_text"] = "核实面试证据并人工审核具体版本后才对外推荐"
    content["recommendation_policy"] = {
        "decision_method": "rubric",
        "required_dimension_ids": ["design", "development", "delivery"],
    }
    content["research_config_ref"] = {"config_id": "unavailable", "version": 1}
    saved = api.patch(
        f"/api/v1/jobs/{job['id']}/rules/draft",
        json={"expected_draft_revision": draft["draft_revision"], "content": content},
    )
    assert saved.status_code == 200, saved.text
    rule = post(
        api,
        f"/jobs/{job['id']}/rules/publish",
        {
            "expected_draft_revision": saved.json()["draft_revision"],
            "d01_ref": job["d01_ref"],
            "d02_ref": job["d02_ref"],
            "is_test_rule": False,
            "confirmation_note": "隔离测试人工确认，不代表真实供应商验收",
        },
    )
    return job["id"], accepted, rule


def import_resume(api, runtime, job_id):
    imported = post(
        api,
        f"/jobs/{job_id}/resume-batches",
        {
            "execution_mode": "live",
            "items": [
                {
                    "client_item_id": "fixture-all-sections",
                    "name": "fictional.txt",
                    "text": RESUME_TEXT,
                }
            ],
        },
        expected=202,
    )
    drain(runtime)
    return imported["items"][0]["application_id"]


def test_material_driven_pipeline_publishes_versions_and_combines_d05_d06(
    api, runtime, monkeypatch
):
    calls = setup_model(runtime, monkeypatch)
    job_id, accepted, rule = publish_material_job(api, runtime)
    application_id = import_resume(api, runtime, job_id)
    assert calls == [
        "job_analysis",
        "interview_standard",
        "screening_standard",
        "resume_parse",
        "screening",
    ]
    with Session(runtime[1]) as db:
        application = db.get(Application, application_id)
        assert application.screening_result == "passed"
        artifacts = {
            kind: latest(db, job_id, kind, application_id if kind not in {"D01", "D02"} else None)
            for kind in ["D01", "D02", "D03", "D04", "D05", "D06"]
        }
        assert artifacts["D06"].content["score_summary"]["coverage"] == 95
        assert artifacts["D06"].content["score_summary"]["total"] is None
        assert len(artifacts["D03"].content["research_objects"]) == 10
        assert artifacts["D02"].content["confirmation_status"] == "confirmed"
        assert all(d["weight"] is not None for d in artifacts["D02"].content["dimensions"])
        assert db.get(Task, accepted["task_id"]).payload["continuation_task_id"]
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "screening.passed"))
        assert validate_handoff(db, event).rule_pack_ref.version == rule["version"]
        for kind, artifact in artifacts.items():
            view = artifact_view(db, artifact)
            if kind != "D04":
                assert not view["content_markdown"].startswith("```json")
        d05_view, d06_view = (artifact_view(db, artifacts[k]) for k in ["D05", "D06"])
        assert d05_view["content_markdown"] == d06_view["content_markdown"]
        assert "待核实" in d06_view["content_markdown"]
        assert len(list(db.scalars(select(ModelUsage)))) == 5
    drain(runtime)
    assert len(calls) == 5


@pytest.mark.parametrize("proposed,conflict", [("rejected", False), ("passed", True)])
def test_routing_does_not_reject_missing_information_or_pass_core_conflict(
    api, runtime, monkeypatch, proposed, conflict
):
    def transform(output):
        output["proposed_result"] = proposed
        output["unresolved_core_conflicts"] = ["主体存在冲突，需核实"] if conflict else []

    setup_model(runtime, monkeypatch, transform)
    job_id, _, _ = publish_material_job(api, runtime)
    application_id = import_resume(api, runtime, job_id)
    assert (
        api.get(f"/api/v1/applications/{application_id}").json()["screening_result"]
        == "manual_review"
    )


def test_new_standard_tasks_refuse_to_overwrite_human_draft_edits(api, runtime, monkeypatch):
    setup_model(runtime, monkeypatch)
    job = post(
        api, "/jobs", {"title": "后端工程师", "company": "虚构研究公司", "material_text": JOB_TEXT}
    )
    post(
        api,
        f"/jobs/{job['id']}/analyze",
        {"expected_revision": 1, "execution_mode": "live"},
        expected=202,
    )
    assert run_once(*runtime)
    with Session(runtime[1]) as db, db.begin():
        row = db.get(IntakeJob, job["id"])
        row.draft_revision += 1
        row.draft = {"screening_text": "人工新草案"}
    drain(runtime)
    with Session(runtime[1]) as db:
        task = db.scalar(select(Task).where(Task.kind == "interview_standard"))
        assert task.status == "failed" and task.error_code == "VERSION_CONFLICT"
        assert db.get(IntakeJob, job["id"]).draft["screening_text"] == "人工新草案"


def test_complete_form_correction_keeps_metadata_and_invalidates_downstream(
    api, runtime, monkeypatch
):
    setup_model(runtime, monkeypatch)
    job_id, _, _ = publish_material_job(api, runtime)
    application_id = import_resume(api, runtime, job_id)
    with Session(runtime[1]) as db:
        before = latest(db, job_id, "D03", application_id)
        ref = artifact_ref(before)
        evidence = before.evidence_refs[0]
        record_id = before.content["resume_form"]["sections"]["基本信息"][0]["record_id"]
    changed = post(
        api,
        f"/applications/{application_id}/corrections",
        {
            "target_artifact_ref": ref,
            "changes": [
                {
                    "path": f"/resume_form/基本信息/{record_id}/当前岗位",
                    "value": {
                        "value": "资深后端工程师",
                        "quote": "候选人补充：资深后端工程师",
                        "status": "stated",
                    },
                    "reason": "授权补充岗位信息",
                }
            ],
            "evidence_refs": [evidence],
            "reason": "人工核实岗位名称后更正",
        },
    )
    assert changed["requires_recompute"]
    with Session(runtime[1]) as db:
        d03 = latest(db, job_id, "D03", application_id)
        assert len(d03.content["resume_form"]["sections"]) == 9
        assert len(d03.content["research_objects"]) == 10
        assert d03.content["document_metadata"]["filename"] == "fictional.txt"
        assert d03.content["facts"]["current_role"]["value"] == "资深后端工程师"
        assert artifact_view(db, d03)["structured_content"]["resume_form"]
        assert latest(db, job_id, "D06", application_id) is None
        assert (
            db.scalar(
                select(OutboxEvent).where(OutboxEvent.event_type == "screening.passed")
            ).status
            == "invalidated"
        )


def test_resource_changes_do_not_replay_a_task_with_new_prompts(api, runtime, monkeypatch):
    calls = setup_model(runtime, monkeypatch)
    job = post(
        api, "/jobs", {"title": "后端工程师", "company": "虚构研究公司", "material_text": JOB_TEXT}
    )
    accepted = post(
        api,
        f"/jobs/{job['id']}/analyze",
        {"expected_revision": 1, "execution_mode": "live"},
        expected=202,
    )
    monkeypatch.setattr("app.modules.intake.agent_prompts.resource_fingerprint", lambda: "changed")
    drain(runtime)
    with Session(runtime[1]) as db:
        task = db.get(Task, accepted["task_id"])
        assert task.status == "failed" and task.error_code == "AGENT_RESOURCES_CHANGED"
    assert calls == []


def test_explicit_job_metadata_is_evidence_without_inventing_missing_fields(
    api, runtime, monkeypatch
):
    setup_model(runtime, monkeypatch)
    job = post(
        api,
        "/jobs",
        {
            "title": "后端工程师",
            "company": "虚构研究公司",
            "location": "虚构城市",
            "salary": "税前固定年薪30万元/年",
            "material_text": JOB_TEXT,
        },
    )
    post(
        api,
        f"/jobs/{job['id']}/analyze",
        {"expected_revision": 1, "execution_mode": "live"},
        expected=202,
    )
    drain(runtime)
    with Session(runtime[1]) as db:
        d01 = latest(db, job["id"], "D01")
        assert d01.content["job_form"]["fields"]["工作地点"]["value"] == "虚构城市"
        assert d01.content["job_form"]["fields"]["用人部门"]["status"] == "unknown"
        task = db.scalar(select(Task).where(Task.kind == "job_analysis"))
        assert task.status == "completed" and len(task.result_refs) == 2


def test_manual_review_keeps_combined_report_and_explicit_reason(api, runtime, monkeypatch):
    setup_model(runtime, monkeypatch)
    job_id, _, _ = publish_material_job(api, runtime)
    application_id = import_resume(api, runtime, job_id)
    with Session(runtime[1]) as db:
        d06 = latest(db, job_id, "D06", application_id)
        ref, evidence = artifact_ref(d06), d06.evidence_refs[0]
    reviewed = post(
        api,
        f"/applications/{application_id}/screening-review",
        {
            "expected_d06_ref": ref,
            "result": "manual_review",
            "reason": "人工发现需要进一步核实的核心证据",
            "evidence_refs": [evidence],
        },
    )
    with Session(runtime[1]) as db:
        artifact = db.get(
            Artifact, (reviewed["new_ref"]["artifact_id"], reviewed["new_ref"]["version"])
        )
        markdown = artifact_view(db, artifact)["content_markdown"]
        assert "D05" in markdown and "D06" in markdown
        assert "人工发现需要进一步核实的核心证据" in markdown
