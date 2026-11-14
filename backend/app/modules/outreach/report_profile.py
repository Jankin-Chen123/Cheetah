"""Customer career section from explicit D03 fields, without model additions."""


def professional_profile(upstream):
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
    for key, label in [("current_city", "当前城市"), ("current_role", "当前岗位")]:
        lines.append(f"{label}：{text(profile.get(key))}")
    education = resume.get("education", [])
    if isinstance(education, list) and education:
        lines.append("### 教育与培训经历")
        for record in education:
            if isinstance(record, dict):
                lines.append(
                    "；".join(
                        f"{label}：{text(record.get(key))}"
                        for key, label in [
                            ("period", "时间"),
                            ("institution", "学校或机构"),
                            ("major_or_course", "专业或课程"),
                            ("credential", "学历学位或证书"),
                        ]
                    )
                )
    employment = resume.get("employment", [])
    history = []
    lines.append("### 工作经历")
    if isinstance(employment, list):
        for record in employment:
            if not isinstance(record, dict):
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
    if not history:
        lines.append("未提供结构化任职记录，完整履历待补充。")
    job = upstream.get("D01", {})
    return {
        "candidate_display_name": name,
        "recommended_job_title": text(job.get("title")) if isinstance(job, dict) else "待确认",
        "work_history": history,
    }, "\n\n".join(lines)
