"""Fictional material and independent expectations; no candidate data or provider calls."""

from app.modules.intake.form_contracts import (
    DIMENSIONS,
    PORTRAIT_FIELDS,
    RESUME_FIELDS,
    FormRecord,
    SourceFact,
)
from app.modules.intake.form_sources import empty_job_form, empty_resume_form

JOB_TEXT = """客户企业名称：虚构研究公司
岗位名称：后端工程师
负责后端服务设计、Python开发及项目交付。
要求本科，相关工作经验至少三年，近两年持续从事后端开发。
行业为企业软件，优先有服务迁移项目经验。
预算：税前固定年薪30万元/年。
"""
RESUME_TEXT = """姓名：虚构候选人
学历：本科
相关工作年限：5
当前任职公司：虚构甲公司
当前岗位：后端工程师
技能：Python开发
2024—至今在虚构甲公司负责企业软件后端服务设计及项目交付。
2021—2024在虚构乙公司参与后端开发。
项目甲：虚构甲公司服务迁移，角色负责人，团队完成迁移。
项目乙：虚构乙公司接口升级，角色成员。
2024虚构比赛：团队二等奖。
论文：虚构研究论文，预印本，作者自述为共同作者。
专利：虚构专利，申请中。
软著：虚构软著。
开源：虚构开源项目。
认证：虚构认证。
"""


def fact(value, quote=None):
    return SourceFact(value=value, quote=quote or value, status="stated")


def anchors(label):
    return {
        key: f"{label}：{description}"
        for key, description in {
            "low": "已证实缺乏岗位所需的实际经验",
            "limited": "少量参与相关任务但关键环节不足",
            "partial": "承担部分常规任务仍需支持",
            "strong": "独立承担主要任务且能说明行动与结果",
            "excellent": "在复杂情境主导关键决策并有充分成果证据",
        }.items()
    }


def job_output():
    form = empty_job_form()
    for key, value in {
        "客户企业名称": "虚构研究公司",
        "岗位名称": "后端工程师",
        "学历要求": "本科",
        "经验要求": "相关工作经验至少三年",
        "行业经验": "企业软件",
        "转正薪资": "税前固定年薪30万元/年",
    }.items():
        form.fields[key] = fact(value)
    form.jd["岗位职责"] = [fact("负责后端服务设计、Python开发及项目交付")]
    return {"facts": {}, "rules": {}, "job_form": form.model_dump(mode="json")}


def interview_output():
    return {
        "dimensions": [
            {
                "id": key,
                "label": label,
                "rubric": "根据后端岗位要求核实具体工作方法、决策和结果",
                "weight": weight,
                "required_evidence": ["实际访谈中的本人工作案例"],
                "anchors": anchors(label),
                "source_quotes": ["负责后端服务设计、Python开发及项目交付。"],
            }
            for key, label, weight in [
                ("design", "后端服务设计能力", 0.4),
                ("development", "Python开发能力", 0.35),
                ("delivery", "项目交付能力", 0.25),
            ]
        ]
    }


def rubric_output():
    return {
        "dimensions": [
            {
                "id": key,
                "weight": weight,
                "requirement": label + "，按已确认后端岗位要求比对",
                "source_quotes": ["预算：税前固定年薪30万元/年。"]
                if key == "salary"
                else ["负责后端服务设计、Python开发及项目交付。"],
                "anchors": anchors(label),
            }
            for key, (label, weight) in DIMENSIONS.items()
        ],
        "routing_policy": (
            "核心职责与技能等有充分正向证据、无核心冲突可以进入电话；"
            "核心信息不足交人工；多项核心要求有明确显著差距才暂不推荐。"
        ),
        "score_tiebreaker": "同档内证据覆盖全部岗位重点且角色明确取上分，否则取下分",
    }


def resume_output():
    form = empty_resume_form()
    form.parse_status, form.limitations = "completed", []
    basic = form.sections["基本信息"][0].fields
    basic["候选人姓名"], basic["当前任职公司"], basic["当前岗位"] = (
        fact("虚构候选人"),
        fact("虚构甲公司"),
        fact("后端工程师"),
    )
    form.sections["专业技能"][0].fields["专业技能"] = fact("Python开发")

    def add(section, record_id, values):
        fields = {key: SourceFact() for key in RESUME_FIELDS[section]}
        fields.update({key: fact(value) for key, value in values.items()})
        form.sections[section].append(FormRecord(record_id=record_id, fields=fields))

    add("教育经历", "education_1", {"学历": "本科"})
    add(
        "工作经历",
        "company_1",
        {
            "任职公司名称": "虚构甲公司",
            "任职开始时间": "2024",
            "任职结束时间": "至今",
            "主要工作职责": "负责企业软件后端服务设计及项目交付",
        },
    )
    add(
        "工作经历",
        "company_2",
        {
            "任职公司名称": "虚构乙公司",
            "任职开始时间": "2021",
            "任职结束时间": "2024",
            "主要工作职责": "参与后端开发",
        },
    )
    add(
        "项目经历",
        "project_1",
        {
            "项目名称": "项目甲",
            "所属公司": "虚构甲公司",
            "项目背景": "服务迁移",
            "候选人角色": "负责人",
            "项目成果": "团队完成迁移",
        },
    )
    add(
        "项目经历",
        "project_2",
        {"项目名称": "项目乙", "所属公司": "虚构乙公司", "候选人角色": "成员"},
    )
    add(
        "比赛与获奖经历",
        "award_1",
        {"比赛名称": "虚构比赛", "获得奖项": "团队二等奖", "举办时间": "2024"},
    )
    add(
        "论文与科研成果",
        "paper_1",
        {"论文名称": "虚构研究论文", "发表平台": "预印本", "作者信息": "共同作者"},
    )
    for record_id, kind, name in [
        ("patent_1", "专利", "虚构专利"),
        ("copyright_1", "软著", "虚构软著"),
        ("open_1", "开源", "虚构开源项目"),
        ("certificate_1", "认证", "虚构认证"),
    ]:
        add("专利及其他专业成果", record_id, {"成果类别": kind, "成果名称": name})
    return {
        "facts": {"years_experience": {"value": 5, "quote": "相关工作年限：5", "status": "stated"}},
        "resume_form": form.model_dump(mode="json"),
    }


def assessment_output(context):
    source = next(item for item in context["allowed_evidence"] if item["category"] == "E2")
    return {
        "portrait": {key: "根据D03自述整理，个人贡献与成果需进一步核实" for key in PORTRAIT_FIELDS},
        "scores": [
            {
                "dimension_id": key,
                "score": None if key == "salary" else 8,
                "reason": "该维度的简历自述有相关经历，真实性与贡献尚需面试核实",
                "evidence": []
                if key == "salary"
                else [
                    {
                        "evidence_id": source["evidence_id"],
                        "version": source["version"],
                        "category": "E2",
                        "purpose": "检视" + key + "维度的简历阶段证据",
                    }
                ],
            }
            for key in DIMENSIONS
        ],
        "proposed_result": "passed",
        "reasons": [
            "核心职责有相关工作经历自述",
            "Python开发技能有简历陈述",
            "薪资未提及，交电话核实",
        ],
        "core_evidence_sufficient": True,
        "handoff": [
            {
                "dimension_id": "salary",
                "fact": "核实税前固定薪资期望",
                "clue": "D03未提及期望薪资",
                "priority": "normal",
            }
        ],
    }
