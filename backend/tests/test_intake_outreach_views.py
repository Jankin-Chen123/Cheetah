from copy import deepcopy

from app.modules.intake.form_sources import empty_resume_form
from app.modules.outreach.intake_views import outreach_content


def test_resume_read_model_keeps_original_evidence_and_unknown_fields():
    form = empty_resume_form().model_dump(mode="json")
    basic = form["sections"]["基本信息"][0]["fields"]
    basic["候选人姓名"] = {
        "status": "stated",
        "value": "虚构姓名",
        "quote": "虚构姓名",
        "evidence_refs": [{"evidence_id": "e1", "version": 2}],
    }
    basic["当前岗位"] = {"status": "unknown", "value": None, "quote": None}
    content = {"resume_form": form, "profile": {"display_name": "旧摘要"}}
    original = deepcopy(content)
    result = outreach_content("D03", content)
    assert result["display_name"] == "虚构姓名"
    assert result["profile"]["current_role"] is None
    assert result["education"] == [] and result["employment"] == []
    assert result["resume_form"] == form and content == original


def test_job_unknown_salary_is_not_promoted_from_unverified_summary():
    content = {
        "salary": "不可采信摘要",
        "job_form": {
            "fields": {"转正薪资": {"status": "unknown", "value": None}},
            "jd": {
                "岗位职责": [
                    {"status": "stated", "value": "岗位原文"},
                    {"status": "unknown", "value": None},
                ]
            },
        },
    }
    result = outreach_content("D01", content)
    assert result["salary"] is None and result["responsibilities"] == ["岗位原文"]


def test_report_projects_from_full_form_keep_confirmed_field_overrides():
    from app.modules.outreach.report_profile import professional_profile

    form = empty_resume_form().model_dump(mode="json")
    form["sections"]["项目经历"] = [
        {
            "record_id": "p1",
            "fields": {
                "项目名称": {"status": "stated", "value": "虚构供应商项目"},
                "个人职责": {"status": "stated", "value": "定义业务流程"},
                "项目成果": {"status": "unknown", "value": None},
            },
        }
    ]
    original = {"resume_form": form, "projects": [{"role": "经原话确认的个人角色"}]}
    data, rendered = professional_profile({"D03": original})
    assert data["projects"][0]["name"] == "虚构供应商项目"
    assert data["projects"][0]["role"] == "经原话确认的个人角色"
    assert data["projects"][0]["results"] == "待确认"
    assert "定义业务流程" in rendered and original["projects"][0] == {
        "role": "经原话确认的个人角色"
    }
