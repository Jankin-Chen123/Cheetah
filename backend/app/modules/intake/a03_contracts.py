"""A03 domain contract. Tool arguments are untrusted, including model-generated ones."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.contracts import ArtifactRef, EvidenceRef

FIELDS = {
    "professional_work": {
        "identity": "作品名称与公开链接",
        "status": "公开状态与时间",
        "ownership": "候选人角色与成果归属",
    },
    "other_achievement": {
        "identity": "成果原始名称与类别",
        "status": "公开记录与状态",
        "ownership": "候选人角色与成果归属",
    },
    "company": {
        "description": "公司原始简介",
        "identity": "公司身份与任职期",
        "industry": "所属行业及主营业务",
        "products": "核心产品及品牌",
        "customers": "客户、市场及渠道",
        "scale": "规模与发展阶段",
        "business": "商业模式与经营情况",
        "competitiveness": "核心竞争力",
        "historical_context": "任职期间重要动态",
        "management": "创始人与管理团队",
        "contribution": "候选人职责与个人归属待核实",
    },
    "project": {
        "identity": "项目名称与所属主体",
        "goal": "项目目标与业务背景",
        "complexity": "技术或业务复杂度",
        "outcomes": "公开成果与落地",
        "contribution": "个人角色与贡献",
        "differences": "关键差异与未核实",
    },
    "award": {
        "identity": "官方赛事与届次",
        "organizer": "主办方与赛道",
        "scope": "参赛范围与奖项设置",
        "outcomes": "官方获奖记录",
        "ownership": "团队与个人获奖属性",
    },
    "paper": {
        "identity": "论文题目与 DOI",
        "platform": "发表平台与时间",
        "status": "发表与预印本状态",
        "authors": "作者身份消歧",
        "impact": "公开影响信息",
        "ownership": "候选人贡献与归属",
    },
    "patent": {
        "identity": "专利名称与编号",
        "status": "申请与授权状态",
        "authors": "申请人和发明人",
        "ownership": "时间与成果归属",
    },
    "software_copyright": {
        "identity": "软著名称与登记编号",
        "status": "登记状态与时间",
        "ownership": "登记主体与候选人归属",
    },
    "open_source": {
        "identity": "官方仓库与项目",
        "status": "公开项目状态",
        "ownership": "可验证的个人贡献",
    },
    "certification": {
        "identity": "认证名称与核验记录",
        "organizer": "认证机构",
        "status": "认证时间与状态",
        "ownership": "持有人身份",
    },
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Citation(Strict):
    source_id: str = Field(min_length=1, max_length=80)
    quote: str = Field(min_length=1, max_length=3000)
    source_date: str | None = Field(default=None, max_length=40)


class Goal(Strict):
    object_id: str = Field(min_length=1, max_length=64)
    field: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=1000)
    priority: Literal["high", "normal", "low"] = "normal"
    rationale: str = Field(min_length=1, max_length=1000)


class Plan(Strict):
    goals: list[Goal] = Field(min_length=1, max_length=100)


class Search(Strict):
    object_id: str = Field(min_length=1, max_length=64)
    query: str = Field(min_length=2, max_length=500)
    purpose: str = Field(min_length=1, max_length=1000)


class ReadSource(Strict):
    object_id: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, max_length=80)


class Finding(Strict):
    field: str = Field(min_length=1, max_length=64)
    category: Literal["E1", "E3", "U"]
    text: str = Field(min_length=1, max_length=2000)
    citations: list[Citation] = Field(default_factory=list, max_length=8)
    a04_fields: list[str] = Field(default_factory=list, max_length=10)
    applicable_period: str | None = Field(default=None, max_length=80)
    historical_applicability: Literal["confirmed", "current_only", "unknown"] = "unknown"
    conflict_with_a04: bool = False
    personal_identity_fields: list[str] = Field(default_factory=list, max_length=5)


class Identity(Strict):
    status: Literal["confirmed", "uncertain", "unmatched"]
    rationale: str = Field(min_length=1, max_length=2000)
    citations: list[Citation] = Field(default_factory=list, max_length=8)
    a04_anchor_fields: list[str] = Field(default_factory=list, max_length=10)


class ObjectFindings(Strict):
    object_id: str = Field(min_length=1, max_length=64)
    identity: Identity
    findings: list[Finding] = Field(default_factory=list, max_length=50)
    gaps: list[str] = Field(default_factory=list, max_length=30)
    verification_questions: list[str] = Field(default_factory=list, max_length=20)
    stop_reason: Literal["sufficient", "identity_uncertain", "no_sources", "no_new_information"]


class Finish(Strict):
    reason: Literal["sufficient", "identity_uncertain", "no_new_information", "no_sources"]
    summary: str = Field(min_length=1, max_length=3000)


class LoadSkill(Strict):
    name: Literal[
        "company-research", "professional-achievements", "evidence-quality", "report-handoff"
    ]


TOOL_MODELS = {
    "set_research_plan": Plan,
    "search_public_sources": Search,
    "read_public_source": ReadSource,
    "record_object_findings": ObjectFindings,
    "finish_research": Finish,
    "load_skill": LoadSkill,
}


class ResearchFact(BaseModel):
    value: str | float | None
    quote: str | None = None
    status: Literal["stated", "unknown", "conflict"]
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    source_type: Literal["resume", "manual_revision"] = "resume"


class ResearchObject(BaseModel):
    object_id: str
    kind: Literal[
        "company",
        "project",
        "award",
        "paper",
        "patent",
        "software_copyright",
        "open_source",
        "certification",
        "professional_work",
        "other_achievement",
    ]
    name: ResearchFact
    period: ResearchFact | None = None
    parent_object_id: str | None = None
    facts: dict[str, ResearchFact] = Field(default_factory=dict)


class ReportFinding(Finding):
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    validation_notes: list[str] = Field(default_factory=list)


class ReportField(BaseModel):
    field: str
    label: str
    a04_information: list[ResearchFact]
    public_information: list[ReportFinding]
    status: Literal["supported", "analysis", "unknown", "conflict", "self_report_only"]


class ObjectReport(BaseModel):
    object_id: str
    kind: str
    original_name: str | None
    original_period: str | None
    original_information: ResearchObject
    identity: Identity
    state: Literal["completed", "needs_verification", "not_executed"]
    fields: list[ReportField]
    gaps: list[str]
    verification_questions: list[str]
    stop_reason: str


class ResearchReport(BaseModel):
    report_version: Literal["1.0"] = "1.0"
    candidate_id: str
    application_id: str
    job_id: str
    d03_ref: ArtifactRef
    d01_ref: ArtifactRef | None
    status: Literal["completed", "partial", "needs_verification", "not_executed", "tool_failed"]
    objects: list[ObjectReport]
    summary: str
    gaps: list[str]
    verification_questions: list[str]
    sources: list[dict]
    goals: list[Goal]
    execution: dict
    stop_reason: str
