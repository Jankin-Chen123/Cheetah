"""Lossless source-backed labels for the outreach read model, not a second extraction."""

from copy import deepcopy


def stated(fields, key):
    fact = fields.get(key) or {}
    return fact.get("value") if fact.get("status") == "stated" else None


def period(fields, start, end):
    values = [stated(fields, start), stated(fields, end)]
    return " — ".join(str(value) for value in values if value) or None


def outreach_content(kind, content):
    data = deepcopy(content)
    if kind == "D01":
        form = data.get("job_form") or {}
        fields = form.get("fields", {})
        data.update(
            title=stated(fields, "岗位名称"),
            salary=stated(fields, "转正薪资"),
            company_introduction=stated(fields, "客户企业名称"),
            responsibilities=[
                fact["value"]
                for fact in form.get("jd", {}).get("岗位职责", [])
                if fact.get("status") == "stated" and fact.get("value")
            ],
        )
    if kind != "D03" or not data.get("resume_form"):
        return data
    sections = data["resume_form"].get("sections", {})
    basic = (sections.get("基本信息") or [{}])[0].get("fields", {})
    profile = {
        **(data.get("profile") or {}),
        "current_city": stated(basic, "所在城市"),
        "current_employer": stated(basic, "当前任职公司"),
        "current_role": stated(basic, "当前岗位"),
    }
    data.update(display_name=stated(basic, "候选人姓名"), profile=profile)
    data["education"] = [
        {
            "period": period(row["fields"], "入学时间", "毕业时间"),
            "institution": stated(row["fields"], "学校名称"),
            "major_or_course": stated(row["fields"], "所学专业"),
            "credential": stated(row["fields"], "学历"),
            "notes": stated(row["fields"], "其他教育信息"),
        }
        for row in sections.get("教育经历", [])
    ]
    data["employment"] = [
        {
            "period": period(row["fields"], "任职开始时间", "任职结束时间"),
            "company": stated(row["fields"], "任职公司名称"),
            "position": stated(row["fields"], "岗位名称"),
            "company_business": stated(row["fields"], "公司相关描述"),
            "responsibilities": [value] if (value := stated(row["fields"], "主要工作职责")) else [],
            "achievements": [value] if (value := stated(row["fields"], "核心工作成果")) else [],
        }
        for row in sections.get("工作经历", [])
    ]
    original_projects = data.get("projects") or []
    data["projects"] = [
        {
            "name": stated(row["fields"], "项目名称"),
            "background": stated(row["fields"], "项目背景"),
            "role": stated(row["fields"], "候选人角色"),
            "actions": stated(row["fields"], "个人职责"),
            "results": stated(row["fields"], "项目成果"),
            **(
                original_projects[index]
                if index < len(original_projects) and isinstance(original_projects[index], dict)
                else {}
            ),
        }
        for index, row in enumerate(sections.get("项目经历", []))
    ]
    return data
