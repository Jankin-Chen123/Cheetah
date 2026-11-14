"""Customer career section from explicit D03 fields, without model additions."""


def professional_profile(upstream, minutes=None):
    resume = upstream.get("D03", {})
    if not isinstance(resume, dict):
        resume = {}
    profile = resume.get("profile", {})
    if not isinstance(profile, dict):
        profile = {}

    def text(value):
        return value.strip() if isinstance(value, str) and value.strip() else "待确认"

    name = text(resume.get("display_name") or profile.get("display_name"))
    lines = [
        "## 第二部分｜候选人职业资料",
        f"候选人：{name}",
        "资料来源：候选人履历自述；未经独立核实。",
    ]
    for key, label in [
        ("current_city", "当前城市"),
        ("current_employer", "当前任职公司"),
        ("current_role", "当前岗位"),
        ("current_employment_status", "在职状态"),
        ("professional_direction", "专业方向"),
    ]:
        lines.append(f"{label}：{text(profile.get(key))}")
    education = resume.get("education", [])
    if isinstance(education, list) and education:
        lines.append("### 教育与培训经历")
        lines.extend(
            [
                "| 起止时间 | 学校/机构 | 专业/课程 | 学历/证书 | 说明 |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for record in education:
            if isinstance(record, dict) and record:
                lines.append(
                    "| "
                    + " | ".join(
                        text(record.get(key)).replace("|", "&#124;").replace("\n", " ")
                        for key in [
                            "period",
                            "institution",
                            "major_or_course",
                            "credential",
                            "notes",
                        ]
                    )
                    + " |"
                )
    employment = resume.get("employment", [])
    history = []
    lines.append("### 工作经历")
    if isinstance(employment, list):
        for record in employment:
            if not isinstance(record, dict) or not record:
                continue
            selected = {
                key: text(record.get(key))
                for key in [
                    "period",
                    "company",
                    "position",
                    "department",
                    "reports_to",
                    "team_scope",
                    "reason_for_leaving",
                    "company_business",
                ]
            }
            for key in ["responsibilities", "achievements"]:
                value = record.get(key, [])
                selected[key] = (
                    [item.strip() for item in value if isinstance(item, str) and item.strip()]
                    if isinstance(value, list)
                    else []
                )
            history.append(selected)
            lines.extend(
                [
                    f"### {selected['company']} · {selected['position']}",
                    f"任职时间：{selected['period']}",
                    f"部门：{selected['department']}；汇报对象：{selected['reports_to']}；团队范围：{selected['team_scope']}",
                ]
            )
            lines.extend(f"职责：{item}" for item in selected["responsibilities"])
            lines.extend(f"自述成果：{item}" for item in selected["achievements"])
            lines.append(f"离职原因：{selected['reason_for_leaving']}")
            if selected["company_business"] != "待确认":
                lines.append(f"企业业务或行业：{selected['company_business']}")
    if not history:
        lines.append("未提供结构化任职记录，完整履历待补充。")
    else:
        overview = [
            "### 工作经历总览",
            "| 任职时间 | 公司 | 职位/部门 | 主要职责 |",
            "| --- | --- | --- | --- |",
        ]
        overview.extend(
            "| "
            + " | ".join(
                value.replace("|", "&#124;").replace("\n", " ")
                for value in (
                    record["period"],
                    record["company"],
                    record["position"] + " / " + record["department"],
                    "；".join(record["responsibilities"]) or "待确认",
                )
            )
            + " |"
            for record in history
        )
        lines[lines.index("### 工作经历") : lines.index("### 工作经历")] = overview
    additional = {}
    for key, label in [
        ("professional_skills", "专业能力与岗位相关技能"),
        ("qualifications", "专业资格"),
        ("additional_projects_or_results", "重要项目与专业成果"),
        ("career_preferences", "求职条件与补充说明"),
    ]:
        values = resume.get(key, [])
        values = (
            [value.strip() for value in values if isinstance(value, str) and value.strip()]
            if isinstance(values, list)
            else []
        )
        additional[key] = values
        if values:
            lines.append(f"### {label}")
            lines.extend(values)
    preferences = resume.get("job_preferences", {})
    if not isinstance(preferences, dict):
        preferences = {}
    preference_fields = [
        ("target_role", "意向岗位"),
        ("target_location", "意向地点"),
        ("salary_expectation", "薪酬要求与口径"),
        ("availability", "可到岗时间"),
        ("other_conditions", "其他必要条件"),
    ]
    lines.append("### 求职条件与意向")
    selected_preferences = {key: text(preferences.get(key)) for key, _ in preference_fields}
    lines.extend(f"{label}：{selected_preferences[key]}" for key, label in preference_fields)
    lines.append("薪酬保留原始币种、月/年及税前税后表述；未提供口径不推算。")
    projects = []
    for record in resume.get("projects", []) if isinstance(resume.get("projects"), list) else []:
        if not isinstance(record, dict) or not record:
            continue
        project = {
            key: text(record.get(key))
            for key in ["name", "background", "role", "actions", "results"]
        }
        projects.append(project)
        lines.extend(
            [
                f"### 重点项目与专业成果｜{project['name']}",
                f"背景与场景：{project['background']}",
                f"个人角色：{project['role']}",
                f"实际行动：{project['actions']}",
                f"成果与原始口径：{project['results']}",
            ]
        )
    # Unstructured oral statements cannot safely overwrite individual resume fields.
    # Preserve exact candidate wording and both sources until a field is confirmed.
    supplements = []
    for fact in (minutes or {}).get("facts", []):
        if fact.get("kind") == "intention" and isinstance(fact.get("quote"), str):
            quote = fact["quote"].strip()
            if quote and quote not in supplements:
                supplements.append(quote)
    if supplements:
        lines.append("### 本次沟通的求职条件补充")
        lines.extend(f"候选人原话：{quote}" for quote in supplements)
        lines.append("以上为本次沟通自述；与履历不一致的字段须确认后再更新。")
    conflicts = [item for item in (minutes or {}).get("conflicts", []) if isinstance(item, str)]
    if conflicts:
        lines.append("### 职业资料待核事项")
        lines.append("履历与本次沟通存在未解决的信息差异，需确认后再使用相关字段。")
    job = upstream.get("D01", {})
    return {
        "candidate_display_name": name,
        "recommended_job_title": text(job.get("title")) if isinstance(job, dict) else "待确认",
        "work_history": history,
        "projects": projects,
        "job_preferences": selected_preferences,
        "current_city": text(profile.get("current_city")),
        "current_employment_status": text(profile.get("current_employment_status")),
        **additional,
        "interview_career_statements": supplements,
        "unresolved_conflicts": conflicts,
    }, "\n\n".join(lines)
