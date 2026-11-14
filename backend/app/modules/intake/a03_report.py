"""Render the user's five-section D04 form from checked research state, never model prose."""

from collections import Counter

from app.modules.intake.a03_contracts import FIELDS, ResearchReport
from app.modules.intake.a03_state import unknown_identity

ALIASES = {
    "identity": ["name", "period", "company", "official_name", "identifier"],
    "contribution": ["role", "contribution", "metrics"],
    "ownership": ["authors", "role", "ownership", "contribution"],
    "historical_context": ["period"],
}
CORE_FIELDS = {
    "company": {"industry", "products"},
    "project": {"goal", "outcomes"},
    "award": {"organizer", "outcomes"},
    "paper": {"platform", "status"},
    "patent": {"status"},
    "software_copyright": {"status"},
    "open_source": {"status"},
    "certification": {"organizer", "status"},
}


def build_report(state: dict, *, candidate_id, application_id, job_id, d03_ref, d01_ref, execution):
    objects, all_gaps, questions = [], [], []
    for item in state["objects"]:
        object_id = item["object_id"]
        record = state.get("records", {}).get(object_id)
        findings = record["findings"] if record else []
        facts = {"name": item["name"], "period": item.get("period"), **item["facts"]}
        fields = []
        for key, label in FIELDS[item["kind"]].items():
            original = [facts[k] for k in ALIASES.get(key, [key]) if facts.get(k)]
            public = [finding for finding in findings if finding["field"] == key]
            categories = {finding["category"] for finding in public}
            status = (
                "conflict"
                if any(f["conflict_with_a04"] for f in public)
                else "unknown"
                if "U" in categories
                else "supported"
                if "E1" in categories
                else "analysis"
                if "E3" in categories
                else "self_report_only"
                if any(f["status"] == "stated" for f in original)
                else "unknown"
            )
            fields.append(
                {
                    "field": key,
                    "label": label,
                    "a04_information": original,
                    "public_information": public,
                    "status": status,
                }
            )
        identity = record["identity"] if record else unknown_identity("本对象尚未完成公开核实")
        goals = [g for g in state.get("goals", []) if g["object_id"] == object_id]
        supported = {f["field"] for f in fields if f["status"] == "supported"}
        complete = bool(
            record
            and record["stop_reason"] == "sufficient"
            and identity["status"] == "confirmed"
            and goals
            and CORE_FIELDS[item["kind"]] <= supported
            and all(goal["field"] in supported for goal in goals if goal["priority"] == "high")
            and not record["gaps"]
        )
        gaps = list(record["gaps"]) if record else ["尚未完成公开检索与核实"]
        if identity["status"] != "confirmed":
            gaps.append("主体身份待核实")
        if record:
            gaps.extend("核心字段尚未核实：" + key for key in CORE_FIELDS[item["kind"]] - supported)
        gaps.extend(note for finding in findings for note in finding.get("validation_notes", []))
        object_questions = list(record["verification_questions"]) if record else []
        if item["kind"] in {"company", "project"}:
            object_questions.append("请核实本人职责、关键行动及量化成果归因")
        objects.append(
            {
                "object_id": object_id,
                "kind": item["kind"],
                "original_name": str(item["name"]["value"])
                if item["name"]["value"] is not None
                else None,
                "original_period": str(item["period"]["value"])
                if item.get("period") and item["period"]["value"] is not None
                else None,
                "original_information": item,
                "identity": identity,
                "state": "completed"
                if complete
                else "needs_verification"
                if record
                else "not_executed",
                "fields": fields,
                "gaps": sorted(set(gaps)),
                "verification_questions": object_questions,
                "stop_reason": record["stop_reason"]
                if record
                else state.get("stop_reason", "not_executed"),
            }
        )
        all_gaps.extend(f"{object_id}: {gap}" for gap in gaps)
        questions.extend(f"{object_id}: {question}" for question in object_questions)
    executed = execution["searches"] + execution["pages"] > 0
    status = (
        "completed"
        if objects and all(o["state"] == "completed" for o in objects)
        else "partial"
        if executed
        else "not_executed"
    )
    if state.get("stop_reason") == "tool_failed":
        status = "tool_failed"
    return ResearchReport.model_validate(
        {
            "candidate_id": candidate_id,
            "application_id": application_id,
            "job_id": job_id,
            "d03_ref": d03_ref,
            "d01_ref": d01_ref,
            "status": status,
            "objects": objects,
            "summary": state.get("summary", "按实际已取得证据交付；未完成内容保留未知"),
            "gaps": sorted(set(all_gaps)),
            "verification_questions": sorted(set(questions)),
            "sources": [
                {k: v for k, v in source.items() if k != "text"}
                for source in state["sources"].values()
            ],
            "goals": state.get("goals", []),
            "execution": execution,
            "stop_reason": state.get("stop_reason", "not_executed"),
        }
    ).model_dump(mode="json")


def cell(value):
    return str(value if value is not None else "未知").replace("|", "\\|").replace("\n", "<br>")


def render_report(report: dict) -> str:
    lines = [
        "# 候选人背景信息与专业成果研究报告",
        "",
        "D04 标准输出表单 V1.0",
        "",
        "## 一、任务概览及研究对象",
        "",
        "|候选人编号|D03 来源与版本|关联岗位|研究状态|",
        "|---|---|---|---|",
        "|"
        + "|".join(cell(report[key]) for key in ("candidate_id", "d03_ref", "job_id", "status"))
        + "|",
        "",
        "|对象|类型|已有原名与期间|状态|",
        "|---|---|---|---|",
    ]
    for item in report["objects"]:
        lines.append(
            f"|{cell(item['object_id'])}|{cell(item['kind'])}|"
            f"{cell(item['original_name'])} / {cell(item['original_period'])}|"
            f"{cell(item['state'])}|"
        )
    for title, kinds in (
        ("二、任职公司研究", {"company"}),
        ("三、项目及个人业绩背景", {"project"}),
        ("四、比赛、论文、专利与其他专业成果", set(FIELDS) - {"company", "project"}),
    ):
        lines.extend(["", "## " + title, ""])
        selected = [item for item in report["objects"] if item["kind"] in kinds]
        if not selected:
            lines.append("D03 未提供此类研究对象；未生成虚构记录。")
        for item in selected:
            lines.extend(
                [
                    "",
                    "### " + cell(item["original_name"]),
                    "",
                    f"原始期间：{cell(item['original_period'])}；身份：{cell(item['identity']['status'])}",
                    "",
                    "|研究项|A04 已有信息（候选人自述 E2）|A03 公开核实与背景补充|证据与时间|",
                    "|---|---|---|---|",
                ]
            )
            for field in item["fields"]:
                original = "；".join(f["quote"] or "未提及" for f in field["a04_information"])
                findings = field["public_information"]
                public = "；".join(f"[{f['category']}] {f['text']}" for f in findings)
                sources = "；".join(
                    f"{c['source_id']}，{c['source_date'] or '时间未知'}：{c['quote']}"
                    for f in findings
                    for c in f["citations"]
                )
                lines.append(
                    "|"
                    + "|".join(
                        cell(value)
                        for value in (
                            field["label"],
                            original or "未提及",
                            public or "U：暂未找到可靠记录",
                            sources or field["status"],
                        )
                    )
                    + "|"
                )
            lines.extend(["", "待核实：" + cell("；".join(item["gaps"]) or "没有额外关键缺口")])
    lines.extend(["", "## 五、研究结论与下游交接", "", cell(report["summary"]), ""])
    for item in report["objects"]:
        lines.append(
            f"- {cell(item['original_name'])}：{cell(item['state'])}；"
            f"停止原因：{cell(item['stop_reason'])}"
        )
    lines.extend(["", "### 关键待核实事实", ""])
    lines.extend("- " + cell(question) for question in report["verification_questions"])
    lines.extend(["", "### 来源", ""])
    for source in report["sources"]:
        lines.append(
            f"- {cell(source['source_id'])}：{cell(source['title'])} — "
            f"{cell(source['url'])}；{cell(source.get('source_date'))}"
        )
    counts = dict(Counter(item["kind"] for item in report["objects"]))
    lines.extend(
        [
            "",
            "研究对象数量：" + cell(counts),
            "",
            "资源消耗与停止：" + cell(report["execution"]),
            "",
            "停止原因：" + cell(report["stop_reason"]),
            "",
            "E1：公开事实；E2：候选人自述；E3：解释性分析；U：未知或待核实。",
            "A03 不提供匹配分数或录用判断；研究未果不等于经历虚假。",
        ]
    )
    return "\n".join(lines) + "\n"
