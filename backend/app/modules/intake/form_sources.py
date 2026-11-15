"""Check extraction provenance and build the A04 -> A03 handoff without a model."""

import re

from app.modules.intake.form_contracts import (
    JD_FIELDS,
    JOB_FIELDS,
    RESUME_FIELDS,
    JobForm,
    ResumeForm,
)


def iter_form_facts(form):
    if isinstance(form, JobForm):
        yield from form.fields.items()
        for section, statements in form.jd.items():
            for index, fact in enumerate(statements):
                yield f"jd/{section}/{index}", fact
    else:
        for section, records in form.sections.items():
            for record in records:
                for key, fact in record.fields.items():
                    yield f"{section}/{record.record_id}/{key}", fact


def source_quote(text: str, quote: str | None) -> str | None:
    """Locate a continuous original span, tolerating whitespace and paired Markdown emphasis."""
    if not quote:
        return None
    if quote in text:
        return quote

    def normalized(value):
        excluded = set()
        for pattern in (
            r"(?<!\*)\*\*(?!\*)(.+?)(?<!\*)\*\*(?!\*)",
            r"(?<!_)__(?!_)(.+?)(?<!_)__(?!_)",
        ):
            for match in re.finditer(pattern, value, re.DOTALL):
                excluded.update(range(match.start(), match.start() + 2))
                excluded.update(range(match.end() - 2, match.end()))
        positions = [
            index
            for index, character in enumerate(value)
            if not character.isspace() and index not in excluded
        ]
        return "".join(value[index] for index in positions), positions

    haystack, positions = normalized(text)
    needle, _ = normalized(quote)
    if not needle:
        return None
    start = haystack.find(needle)
    return None if start < 0 else text[positions[start] : positions[start + len(needle) - 1] + 1]


def check_form_sources(form, text):
    if isinstance(form, ResumeForm):
        form.sections = {key: form.sections[key] for key in RESUME_FIELDS}
        for key, records in form.sections.items():
            for record in records:
                record.fields = {field: record.fields[field] for field in RESUME_FIELDS[key]}
    for _, fact in iter_form_facts(form):
        # Never accept model-supplied database references.
        fact.evidence_refs = []
        if fact.status != "stated":
            continue
        fact.quote = source_quote(text, fact.quote)

        def normalize(value):
            return re.sub(r"\s+", "", value).casefold()

        numeric_values = re.findall(r"\d+(?:\.\d+)?", fact.value or "")
        numbers_supported = all(
            re.search(r"(?<![\d.])" + re.escape(number) + r"(?![\d.])", fact.quote or "")
            for number in numeric_values
        )
        if (
            not fact.quote
            or fact.quote not in text
            or normalize(fact.value) not in normalize(fact.quote)
            or not numbers_supported
        ):
            fact.value, fact.quote, fact.status = None, None, "unknown"
            fact.note = "提取值或引用缺少原文支持，需核实"
            if isinstance(form, ResumeForm):
                form.parse_status = "partial"
    return form


def empty_job_form():
    return JobForm(fields={key: {} for key in JOB_FIELDS}, jd={key: [] for key in JD_FIELDS})


def empty_resume_form():
    sections = {key: [] for key in RESUME_FIELDS}
    for index, key in enumerate(("基本信息", "专业技能", "信息缺失与异常")):
        sections[key] = [
            {"record_id": f"singleton_{index}", "fields": {name: {} for name in RESUME_FIELDS[key]}}
        ]
    return ResumeForm(
        parse_status="partial", sections=sections, limitations=["模拟提取不代表真实模型分析"]
    )


def resume_objects(form: ResumeForm) -> list[dict]:
    """Every actual record produces an object. No private contacts enter this list."""
    objects = []
    layouts = {
        "工作经历": (
            "company",
            "任职公司名称",
            {
                "description": "公司相关描述",
                "role": "岗位名称",
                "contribution": "主要工作职责",
                "metrics": "量化业绩数据",
            },
        ),
        "项目经历": (
            "project",
            "项目名称",
            {
                "company": "所属公司",
                "description": "项目背景",
                "goal": "项目目标",
                "role": "候选人角色",
                "contribution": "个人职责",
                "actions": "关键行动",
                "complexity": "技术或方法",
                "outcomes": "项目成果",
                "metrics": "量化结果",
                "link": "项目链接",
            },
        ),
        "比赛与获奖经历": (
            "award",
            "比赛名称",
            {
                "year": "举办时间",
                "outcomes": "获得奖项",
                "track": "所属赛道",
                "organizer": "主办机构",
                "ownership": "参赛形式",
                "role": "候选人角色",
                "contribution": "相关成果",
                "link": "证明链接",
            },
        ),
        "论文与科研成果": (
            "paper",
            "论文名称",
            {
                "year": "发表年份",
                "platform": "发表平台",
                "authors": "作者信息",
                "description": "研究主题",
                "link": "论文链接",
            },
        ),
        "专利及其他专业成果": (
            "patent",
            "成果名称",
            {
                "identifier": "登记号或编号",
                "year": "申请/发布/授权时间",
                "role": "候选人角色",
                "description": "成果描述",
                "link": "证明链接",
            },
        ),
    }

    def as_fact(f):
        return f.model_dump(exclude={"note"})

    for section, (kind, name_key, mapping) in layouts.items():
        for record in form.sections[section]:
            fields = record.fields
            actual_kind = kind
            if section == "专利及其他专业成果":
                category = fields["成果类别"].value or ""
                actual_kind = next(
                    (
                        v
                        for k, v in [
                            ("软著", "software_copyright"),
                            ("开源", "open_source"),
                            ("认证", "certification"),
                            ("证书", "certification"),
                            ("专利", "patent"),
                            ("作品", "professional_work"),
                        ]
                        if k in category
                    ),
                    None,
                )
                if actual_kind is None:
                    actual_kind = "other_achievement"
            period_key = {
                "工作经历": "任职开始时间",
                "项目经历": "起止时间",
                "比赛与获奖经历": "举办时间",
                "论文与科研成果": "发表年份",
                "专利及其他专业成果": "申请/发布/授权时间",
            }[section]
            facts = {key: as_fact(fields[label]) for key, label in mapping.items()}
            if section == "工作经历":
                facts["end_period"] = as_fact(fields["任职结束时间"])
                facts["outcomes"] = as_fact(fields["核心工作成果"])
            objects.append(
                {
                    "object_id": record.record_id,
                    "kind": actual_kind,
                    "name": as_fact(fields[name_key]),
                    "period": as_fact(fields[period_key]),
                    "parent_object_id": None,
                    "facts": facts,
                }
            )
    for obj in objects:
        company = obj["facts"].get("company", {})
        parents = [
            item
            for item in objects
            if item["kind"] == "company"
            and item["name"].get("value") == company.get("value")
            and company.get("value")
        ]
        if len(parents) == 1:
            obj["parent_object_id"] = parents[0]["object_id"]
    return objects


def canonical_resume_facts(form: ResumeForm, *, persisted=False):
    """Compatibility summary uses original facts; the full form remains authoritative."""
    basic = form.sections["基本信息"][0].fields
    skills = form.sections["专业技能"][0].fields
    mapping = {
        "name": basic["候选人姓名"],
        "current_role": basic["当前岗位"],
        "employer": basic["当前任职公司"],
        "location": basic["所在城市"],
        "skills": skills["专业技能"],
    }
    keys = {"value", "quote", "status"} | ({"evidence_refs"} if persisted else set())
    return {
        key: {k: value for k, value in fact.model_dump().items() if k in keys}
        for key, fact in mapping.items()
    }
