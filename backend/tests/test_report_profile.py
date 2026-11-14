from app.modules.outreach.report_profile import professional_profile


def test_profile_preserves_professional_fields_without_private_attributes():
    profile, body = professional_profile(
        {
            "D03": {
                "display_name": "虚构候选人",
                "profile": {
                    "current_employer": "虚构公司",
                    "current_employment_status": "在职",
                    "phone": "PRIVATE_CONTACT",
                    "marital_status": "PRIVATE_ATTRIBUTE",
                },
                "employment": [
                    {
                        "company": "虚构公司",
                        "period": "2023年",
                        "reason_for_leaving": "候选人自述组织调整",
                    }
                ],
                "qualifications": ["虚构岗位资格", None],
                "additional_projects_or_results": ["虚构项目：参与研究"],
                "career_preferences": ["工作地点待协商"],
            }
        }
    )
    assert profile["work_history"][0]["period"] == "2023年"
    assert profile["work_history"][0]["reason_for_leaving"] == "候选人自述组织调整"
    assert profile["qualifications"] == ["虚构岗位资格"]
    assert "当前任职公司：虚构公司" in body
    assert "工作地点待协商" in body
    assert "PRIVATE_CONTACT" not in body
    assert "PRIVATE_ATTRIBUTE" not in body


def test_optional_sections_are_omitted_without_sources():
    profile, body = professional_profile({"D03": {}})
    assert profile["additional_projects_or_results"] == []
    assert "### 重要项目与专业成果" not in body
    assert "### 专业资格" not in body
    assert "完整履历待补充" in body


def test_interview_conditions_keep_exact_wording_and_unresolved_conflicts():
    profile, body = professional_profile(
        {"D03": {"profile": {"current_city": "虚构城市甲"}}},
        {
            "facts": [
                {"kind": "intention", "quote": "期望年薪30万元，税前税后还没确定"},
                {"kind": "other", "quote": "不应被用于求职条件"},
            ],
            "conflicts": ["所在地与履历不一致，待确认"],
        },
    )
    assert "当前城市：虚构城市甲" in body
    assert profile["interview_career_statements"] == ["期望年薪30万元，税前税后还没确定"]
    assert profile["unresolved_conflicts"] == ["所在地与履历不一致，待确认"]
    assert "所在地与履历不一致，待确认" not in body
    assert "存在未解决的信息差异" in body
    assert "不应被用于求职条件" not in body
