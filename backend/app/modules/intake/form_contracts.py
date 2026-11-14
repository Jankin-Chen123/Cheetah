"""Versioned business forms derived from the supplied A01--A05 specifications.

These models describe model output, not model authority. Source checks, arithmetic,
publication and execution decisions are applied separately by the host.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictForm(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class SourceFact(StrictForm):
    value: str | None = Field(default=None, max_length=6000)
    status: Literal["stated", "unknown", "conflict"] = "unknown"
    quote: str | None = Field(default=None, max_length=6000)
    note: str | None = Field(default=None, max_length=1000)
    evidence_refs: list[dict] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def supported_value(self):
        if self.status == "stated" and (not self.value or not self.quote):
            raise ValueError("Stated fields require a value and source quotation")
        if self.status != "stated" and self.value is not None:
            raise ValueError("Unknown/conflicting fields cannot carry a definitive value")
        return self


JOB_GROUPS = {
    "客户企业信息": ["客户企业名称", "客户企业简称", "客户所属行业", "对接 HR", "用人部门"],
    "一、基础信息": ["岗位名称", "所属部门", "直属上级岗位", "下属人数", "工作时间"],
    "二、薪酬与考核": [
        "试用期薪资",
        "转正薪资",
        "固定薪资与浮动薪资",
        "奖金与绩效",
        "薪资发放周期",
        "浮动薪资与绩效指标挂钩",
    ],
    "三、任职要求": [
        "学历要求",
        "经验要求",
        "技能要求—硬技能",
        "技能要求—软技能",
        "行业经验",
        "项目经验",
        "行为特质",
    ],
    "四、工作目标与核心成果": ["短期工作目标", "长期工作目标", "核心成果"],
    "五、团队与部门架构": ["团队结构", "跨部门协作需求"],
    "六、潜在挑战与成长机会": ["工作挑战", "成长机会"],
    "七、目标竞品公司": ["目标竞品公司"],
    "八、工作文化与环境": ["团队文化", "工作地点", "工作地点与流动性", "文化契合度"],
    "九、加分项与其他要求": ["加分项", "隐性门槛", "其他要求"],
}
JOB_FIELDS = [name for names in JOB_GROUPS.values() for name in names]
JD_FIELDS = ["岗位职责", "任职要求", "加分条件"]


class JobForm(StrictForm):
    template_version: Literal["A01-1.5"] = "A01-1.5"
    fields: dict[str, SourceFact] = Field(
        description="Exactly these 38 keys: " + "、".join(JOB_FIELDS)
    )
    jd: dict[str, list[SourceFact]] = Field(
        description="Exactly 岗位职责、任职要求、加分条件; only confirmed source statements"
    )

    @model_validator(mode="after")
    def complete(self):
        if set(self.fields) != set(JOB_FIELDS) or set(self.jd) != set(JD_FIELDS):
            raise ValueError("A01 requires all 38 fields and all three JD sections")
        return self


RESUME_FIELDS = {
    "基本信息": [
        "候选人姓名",
        "联系电话",
        "电子邮箱",
        "所在城市",
        "当前任职公司",
        "当前岗位",
        "求职意向",
    ],
    "教育经历": [
        "学校名称",
        "学历",
        "学位",
        "所学专业",
        "入学时间",
        "毕业时间",
        "学习形式",
        "其他教育信息",
    ],
    "工作经历": [
        "任职公司名称",
        "所属部门",
        "岗位名称",
        "任职开始时间",
        "任职结束时间",
        "主要工作职责",
        "管理职责",
        "核心工作成果",
        "量化业绩数据",
        "公司相关描述",
    ],
    "项目经历": [
        "项目名称",
        "所属公司",
        "起止时间",
        "项目背景",
        "项目目标",
        "候选人角色",
        "个人职责",
        "关键行动",
        "技术或方法",
        "项目成果",
        "量化结果",
        "项目链接",
    ],
    "专业技能": ["专业技能", "技术工具", "管理能力描述", "语言能力", "相关证书", "其他专业能力"],
    "比赛与获奖经历": [
        "比赛名称",
        "举办时间",
        "获得奖项",
        "所属赛道",
        "主办机构",
        "参赛形式",
        "候选人角色",
        "相关成果",
        "证明链接",
    ],
    "论文与科研成果": [
        "论文名称",
        "发表年份",
        "发表平台",
        "作者信息",
        "研究主题",
        "论文链接",
        "其他科研成果",
    ],
    "专利及其他专业成果": [
        "成果类别",
        "成果名称",
        "登记号或编号",
        "申请/发布/授权时间",
        "候选人角色",
        "成果描述",
        "证明链接",
    ],
    "信息缺失与异常": [
        "缺失信息",
        "歧义或识别错误",
        "时间冲突",
        "个人贡献不清晰",
        "量化口径不完整",
        "其他待核实问题",
    ],
}


class FormRecord(StrictForm):
    record_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    fields: dict[str, SourceFact] = Field(max_length=20)


class ResumeForm(StrictForm):
    template_version: Literal["A04-1.1"] = "A04-1.1"
    parse_status: Literal["completed", "partial", "needs_confirmation"]
    sections: dict[str, list[FormRecord]] = Field(
        description="All nine sections with exact per-record fields: " + str(RESUME_FIELDS)
    )
    limitations: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def complete(self):
        if set(self.sections) != set(RESUME_FIELDS):
            raise ValueError("D03 requires nine modules, empty lists for absent repeatable records")
        ids = []
        for section, records in self.sections.items():
            if len(records) > 100:
                raise ValueError("Too many records")
            if section in {"基本信息", "专业技能", "信息缺失与异常"} and len(records) != 1:
                raise ValueError("Singleton sections require one complete record")
            for record in records:
                ids.append(record.record_id)
                if set(record.fields) != set(RESUME_FIELDS[section]):
                    raise ValueError("Incomplete fields in " + section)
        if len(ids) != len(set(ids)):
            raise ValueError("D03 record IDs must be unique")
        return self


DIMENSIONS = {
    "responsibilities": ("核心职责适配度", 25),
    "skills": ("任职要求与技能匹配度", 20),
    "education_experience": ("学历与相关工作年限", 15),
    "recent_relevance": ("最近两年岗位相关性", 15),
    "industry_context": ("行业与业务场景相关性", 10),
    "projects_preferences": ("项目经验与优先条件", 10),
    "salary": ("薪资匹配度", 5),
}


class Anchors(StrictForm):
    low: str = Field(min_length=5, max_length=2000, description="1--2 points, observed mismatch")
    limited: str = Field(min_length=5, max_length=2000, description="3--4 points")
    partial: str = Field(min_length=5, max_length=2000, description="5--6 points")
    strong: str = Field(min_length=5, max_length=2000, description="7--8 points")
    excellent: str = Field(min_length=5, max_length=2000, description="9--10 points")


class ScreeningDimension(StrictForm):
    id: Literal[
        "responsibilities",
        "skills",
        "education_experience",
        "recent_relevance",
        "industry_context",
        "projects_preferences",
        "salary",
    ]
    enabled: bool = True
    weight: float = Field(ge=0, le=100)
    requirement: str = Field(min_length=1, max_length=3000)
    source_quotes: list[str] = Field(default_factory=list, max_length=20)
    anchors: Anchors
    adjustment_reason: str | None = Field(default=None, max_length=1000)
    interview_dimension_ids: list[str] = Field(default_factory=list, max_length=100)


class ScreeningRubric(StrictForm):
    method: Literal["a05-evidence-v2.1"] = "a05-evidence-v2.1"
    dimensions: list[ScreeningDimension] = Field(min_length=7, max_length=7)
    routing_policy: str = Field(
        min_length=20,
        max_length=5000,
        description=(
            "Job-level criteria for core evidence, mismatches and review. "
            "No invented universal cutoff."
        ),
    )
    score_tiebreaker: str = Field(
        min_length=10,
        max_length=2000,
        description="Explain evidence-based choice within each two-point band",
    )
    necessary_qualifications: list[str] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Confirmed indispensable professional licenses only; "
            "never age, gender, reputation or ordinary experience preferences"
        ),
    )

    @model_validator(mode="after")
    def fixed_weights(self):
        if {d.id for d in self.dimensions} != set(DIMENSIONS):
            raise ValueError("Exactly seven distinct A05 dimensions required")
        if abs(sum(d.weight for d in self.dimensions) - 100) > 0.00001:
            raise ValueError("A05 weights must sum to 100")
        for d in self.dimensions:
            if d.enabled and not d.source_quotes:
                raise ValueError("Enabled dimensions need actual job source support")
            if d.enabled != (d.weight > 0):
                raise ValueError(
                    "Disabled dimensions need zero weight, enabled dimensions positive weight"
                )
            if (not d.enabled or d.weight != DIMENSIONS[d.id][1]) and not d.adjustment_reason:
                raise ValueError("Job-level weight changes require a reason")
        return self


class EvidenceUse(StrictForm):
    evidence_id: str
    version: int = Field(ge=1)
    category: Literal["E1", "E2", "E3", "U"]
    purpose: str = Field(min_length=5, max_length=1000)


class DimensionScore(StrictForm):
    dimension_id: str
    score: int | None = Field(default=None, ge=1, le=10)
    reason: str = Field(min_length=10, max_length=3000)
    evidence: list[EvidenceUse] = Field(default_factory=list, max_length=40)
    questions: list[str] = Field(default_factory=list, max_length=20)


class ScoredDimension(DimensionScore):
    label: str
    weight: float
    requirement: str
    interview_dimension_ids: list[str]
    status: Literal["not_applicable", "not_evaluated", "evaluated"]
    weighted_score: float | None


class ScoreSummary(StrictForm):
    weight_total: Literal[100]
    coverage: float = Field(ge=0, le=100)
    contribution: float = Field(ge=0, le=100)
    total: float | None = Field(default=None, ge=0, le=100)
    rows: list[ScoredDimension]


class DocumentMetadata(StrictForm):
    candidate_id: str
    filename: str
    format: str
    file_id: str


class ScreeningAssessment(StrictForm):
    portrait: dict[str, str] = Field(
        description=(
            "Exactly: 教育和相关年限、主要工作经历与职责、专业技能与工作方法、"
            "行业及业务场景、项目及个人贡献、比赛论文等专业成果、"
            "岗位相关优势/迁移能力、已证实差距/信息缺口"
        )
    )
    scores: list[DimensionScore] = Field(min_length=7, max_length=7)
    proposed_result: Literal["passed", "manual_review", "rejected"]
    reasons: list[str] = Field(min_length=3, max_length=5)
    core_evidence_sufficient: bool
    significant_mismatch_dimensions: list[str] = Field(default_factory=list, max_length=7)
    essential_qualification_failure: EvidenceUse | None = None
    failed_qualification: str | None = None
    unresolved_core_conflicts: list[str] = Field(default_factory=list, max_length=30)
    handoff: list[dict[str, str]] = Field(
        default_factory=list,
        max_length=100,
        description=(
            "Each: dimension_id, fact, clue, priority (high/normal/low). "
            "Factual handoff, not scripts."
        ),
    )


PORTRAIT_FIELDS = [
    "教育和相关年限",
    "主要工作经历与职责",
    "专业技能与工作方法",
    "行业及业务场景",
    "项目及个人贡献",
    "比赛论文等专业成果",
    "岗位相关优势/迁移能力",
    "已证实差距/信息缺口",
]
