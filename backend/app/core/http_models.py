"""HTTP response models imported from the V0.1 design, now maintained in Python.

Export runtime OpenAPI after changes; internal event contracts remain separate.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AnyUrl, AwareDatetime, BaseModel, ConfigDict, Field, RootModel

from app.modules.intake.a03_contracts import ResearchObject, ResearchReport
from app.modules.intake.directions import DirectionAssignment, DirectionId
from app.modules.intake.form_contracts import (
    DocumentMetadata,
    JobForm,
    ResumeForm,
    ScoreSummary,
    ScreeningAssessment,
    ScreeningRubric,
)
from app.modules.intake.schemas import (
    InterviewDimension,
    RecommendationPolicy,
    RuleContent,
)


class Health(BaseModel):
    status: Literal["ok"]
    service: Literal["cheeta-api"]
    stage: Literal["initialization"]


class Readiness(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, Literal["ok", "unavailable"]]
    stage: Literal["initialization"]


class ArtifactRef(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    artifact_id: Annotated[str, Field(max_length=128, min_length=1)]
    version: Annotated[int, Field(ge=1)]


class EvidenceRef(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    evidence_id: Annotated[str, Field(max_length=128, min_length=1)]
    version: Annotated[int, Field(ge=1)]


class FileRef(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    file_id: Annotated[str, Field(max_length=128, min_length=1)]
    version: Annotated[int, Field(ge=1)]


class RulePackRef(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    rule_pack_id: Annotated[str, Field(max_length=128, min_length=1)]
    version: Annotated[int, Field(ge=1)]
    publication_status: Literal["published"]
    is_test_rule: bool


class InputRef(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["material", "artifact", "rule_pack", "evidence", "config"]
    id: Annotated[str, Field(max_length=128, min_length=1)]
    version: Annotated[int, Field(ge=1)]


class SourceMode(RootModel[Literal["live", "mock", "manual"]]):
    root: Literal["live", "mock", "manual"]


class StageSources(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    candidate_material: SourceMode | None
    model: SourceMode | None
    research: SourceMode | None
    phone: SourceMode | None


class Provenance(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    source_mode: SourceMode
    inherited_source_modes: list[SourceMode]
    source_modes: StageSources
    fixture_only: bool


class Reason(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    code: Annotated[str, Field(min_length=1)]
    message: Annotated[str, Field(min_length=1)]
    missing_fields: list[str]


class ValidationIssue(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    path: list[str]
    code: str
    message: str


class Error(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    code: str
    message: str
    request_id: Annotated[str, Field(max_length=128, min_length=1)]
    details: dict[str, Any] | list[dict[str, Any]] | None


class ImportLimits(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    max_items: Annotated[int, Field(ge=1)]
    max_file_bytes: Annotated[int, Field(ge=1)]
    max_text_chars: Annotated[int, Field(ge=1)]


class Capabilities(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    modules: list[str]
    mock_execution_allowed: bool
    import_limits: ImportLimits
    model_configured: bool = Field(default=False, description="仅表示配置，未证明供应商可用")
    search_configured: bool = Field(
        default=False, description="仅表示选择了搜索适配器，未证明供应商可用"
    )
    voice_configured: bool = False


class User(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    id: Annotated[str, Field(max_length=128, min_length=1)]
    display_name: Annotated[str, Field(max_length=100, min_length=1)]


class Organization(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    id: Annotated[str, Field(max_length=128, min_length=1)]
    name: Annotated[str, Field(max_length=100, min_length=1)]


class Session(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    user: User
    organization: Organization
    permissions: list[str]
    csrf_token: Annotated[str, Field(min_length=1)]
    expires_at: AwareDatetime
    capabilities: Capabilities


class WorkspaceSummary(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    as_of: AwareDatetime
    source_scope: Literal["all", "live", "mock", "manual"]
    active_job_count: Annotated[int, Field(ge=0)]
    application_count: Annotated[int, Field(ge=0)]
    waiting_call_count: Annotated[int, Field(ge=0)]
    pending_report_count: Annotated[int, Field(ge=0)]


class JobId(RootModel[str]):
    root: Annotated[str, Field(max_length=128, min_length=1)]


class ApplicationId(RootModel[str]):
    root: Annotated[str, Field(max_length=128, min_length=1)]


class Todo(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    id: Annotated[str, Field(max_length=128, min_length=1)]
    type: Literal[
        "rule_confirmation",
        "material_correction",
        "identity_ambiguity",
        "evidence_conflict",
        "screening_review",
        "report_review",
        "external_reconciliation",
        "delivered_report_correction",
    ]
    title: str
    reason: Reason
    resource_type: Literal["job", "application", "call", "report"]
    resource_id: Annotated[str, Field(max_length=128, min_length=1)]
    job_id: JobId | None
    application_id: ApplicationId | None
    created_at: AwareDatetime
    provenance: Provenance


class TaskAccepted(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(max_length=128, min_length=1)]
    resource_type: Literal["job", "batch", "application", "call", "report", "task", "talent"]
    resource_id: Annotated[str, Field(max_length=128, min_length=1)]
    poll_after_ms: Annotated[int, Field(ge=1000)]


class Tokens(RootModel[int]):
    root: Annotated[int, Field(ge=0)]


class SearchCount(RootModel[int]):
    root: Annotated[int, Field(ge=0)]


class CallSeconds(RootModel[int]):
    root: Annotated[int, Field(ge=0)]


class EstimatedCost(RootModel[str]):
    root: Annotated[str, Field(pattern="^\\d+(\\.\\d+)?$")]


class ActualCost(RootModel[str]):
    root: Annotated[str, Field(pattern="^\\d+(\\.\\d+)?$")]


class Usage(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    tokens: Tokens | None
    search_count: SearchCount | None
    call_seconds: CallSeconds | None
    estimated_cost: EstimatedCost | None
    actual_cost: ActualCost | None
    currency: str


class Limit(RootModel[str]):
    root: Annotated[str, Field(pattern="^\\d+(\\.\\d+)?$")]


class Reserved(RootModel[str]):
    root: Annotated[str, Field(pattern="^\\d+(\\.\\d+)?$")]


class Settled(RootModel[str]):
    root: Annotated[str, Field(pattern="^\\d+(\\.\\d+)?$")]


class Estimated(RootModel[str]):
    root: Annotated[str, Field(pattern="^\\d+(\\.\\d+)?$")]


class Remaining(RootModel[str]):
    root: Annotated[str, Field(pattern="^\\d+(\\.\\d+)?$")]


class BudgetCounters(BaseModel):
    limit: int = Field(ge=0)
    reserved: int = Field(ge=0)
    used: int = Field(ge=0)


class Budget(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    limit: Limit | None
    reserved: Reserved | None
    settled: Settled | None
    estimated: Estimated | None
    remaining: Remaining | None
    currency: str
    reconciliation_status: Literal["not_required", "pending", "confirmed", "unknown"]
    model_calls: BudgetCounters | None = None
    model_tokens: BudgetCounters | None = None
    search_calls: BudgetCounters | None = None


class PollAfterMs(RootModel[int]):
    root: Annotated[int, Field(ge=1000)]


class Task(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    id: Annotated[str, Field(max_length=128, min_length=1)]
    continuation_task_id: str | None = None
    kind: Literal[
        "batch",
        "job_analysis",
        "interview_standard",
        "screening_standard",
        "resume_parse",
        "talent_parse",
        "research",
        "screening",
        "interview_outline",
        "interview_extract",
        "evaluation",
        "recommendation",
        "recompute",
        "call_reconcile",
        "call_stop",
    ]
    status: Literal[
        "queued",
        "running",
        "waiting_conditions",
        "awaiting_external",
        "reconciling",
        "completed",
        "failed",
        "cancelled",
    ]
    revision: Annotated[int, Field(ge=1)]
    resource_type: str
    resource_id: Annotated[str, Field(max_length=128, min_length=1)]
    input_refs: list[InputRef]
    result_refs: list[ArtifactRef]
    reason: Reason | None
    error: Error | None
    attempt_count: Annotated[int, Field(ge=0)]
    retryable: bool
    allowed_actions: list[str]
    poll_after_ms: PollAfterMs | None
    usage: Usage
    budget: Budget
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    finished_at: AwareDatetime | None


class Weight(RootModel[float]):
    root: Annotated[float, Field(ge=0.0, le=1.0)]


class RuleDraft(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    job_id: Annotated[str, Field(max_length=128, min_length=1)]
    draft_revision: Annotated[int, Field(ge=1)]
    content: RuleContent
    validation_issues: list[ValidationIssue]
    updated_at: AwareDatetime


class RulePack(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    rule_pack_id: Annotated[str, Field(max_length=128, min_length=1)]
    job_id: Annotated[str, Field(max_length=128, min_length=1)]
    version: Annotated[int, Field(ge=1)]
    publication_status: Literal["published"]
    is_test_rule: bool
    content: RuleContent
    d01_ref: ArtifactRef
    d02_ref: ArtifactRef
    published_by: Annotated[str, Field(max_length=128, min_length=1)]
    published_at: AwareDatetime


class Location(RootModel[str]):
    root: Annotated[str, Field(max_length=100)]


class Salary(RootModel[str]):
    root: Annotated[str, Field(max_length=100)]


class ActiveTaskId(RootModel[str]):
    root: Annotated[str, Field(max_length=128, min_length=1)]


class Counts(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    applications: Annotated[int, Field(ge=0)]
    pending_reports: Annotated[int, Field(ge=0)]


class Job(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    id: Annotated[str, Field(max_length=128, min_length=1)]
    organization_id: Annotated[str, Field(max_length=128, min_length=1)]
    owner_id: Annotated[str, Field(max_length=128, min_length=1)]
    revision: Annotated[int, Field(ge=1)]
    title: Annotated[str, Field(max_length=100, min_length=1)]
    routing_directions: list[DirectionId] = Field(default_factory=list)
    company: Annotated[str, Field(max_length=100, min_length=1)]
    location: Location | None
    salary: Salary | None
    status: Literal["active", "paused", "archived"]
    material_text: Annotated[str, Field(max_length=30000, min_length=1)]
    material_version: Annotated[int, Field(ge=1)]
    unknown_fields: list[str]
    rule_status: Literal[
        "draft", "needs_information", "pending_confirmation", "published", "disabled"
    ]
    published_rule_pack_ref: RulePackRef | None
    draft_revision: Annotated[int, Field(ge=1)]
    d01_ref: ArtifactRef | None = None
    d02_ref: ArtifactRef | None = None
    active_task_ids: list[ActiveTaskId]
    counts: Counts
    provenance: Provenance
    created_at: AwareDatetime
    updated_at: AwareDatetime


class CandidateId(RootModel[str]):
    root: Annotated[str, Field(max_length=128, min_length=1)]


class TaskId(RootModel[str]):
    root: Annotated[str, Field(max_length=128, min_length=1)]


class DuplicateOfItemId(RootModel[str]):
    root: Annotated[str, Field(max_length=128, min_length=1)]


class ReplacesItemId(RootModel[str]):
    root: Annotated[str, Field(max_length=128, min_length=1)]


class BatchItem(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    id: Annotated[str, Field(max_length=128, min_length=1)]
    batch_id: Annotated[str, Field(max_length=128, min_length=1)]
    client_item_id: Annotated[str, Field(max_length=128, min_length=1)]
    revision: Annotated[int, Field(ge=1)]
    name: str
    state: Literal[
        "queued",
        "processing",
        "completed",
        "duplicate",
        "invalid",
        "failed",
        "cancelled",
    ]
    file_ref: FileRef | None
    candidate_id: CandidateId | None
    application_id: ApplicationId | None
    task_id: TaskId | None
    duplicate_of_item_id: DuplicateOfItemId | None
    replaces_item_id: ReplacesItemId | None
    error: Error | None
    created_at: AwareDatetime


class Counts1(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    total: Annotated[int, Field(ge=0)]
    queued: Annotated[int, Field(ge=0)]
    processing: Annotated[int, Field(ge=0)]
    completed: Annotated[int, Field(ge=0)]
    failed: Annotated[int, Field(ge=0)]
    duplicate: Annotated[int, Field(ge=0)]
    cancelled: Annotated[int, Field(ge=0)]


class Batch(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    id: Annotated[str, Field(max_length=128, min_length=1)]
    job_id: Annotated[str, Field(max_length=128, min_length=1)]
    task_id: Annotated[str, Field(max_length=128, min_length=1)]
    status: Literal["queued", "processing", "partial_failed", "completed", "failed", "cancelled"]
    rule_pack_ref: RulePackRef
    counts: Counts1
    provenance: Provenance
    created_at: AwareDatetime
    updated_at: AwareDatetime


class BatchItemReceipt(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    item_id: Annotated[str, Field(max_length=128, min_length=1)]
    client_item_id: Annotated[str, Field(max_length=128, min_length=1)]
    disposition: Literal["accepted", "duplicate", "invalid"]
    application_id: ApplicationId | None
    error: Error | None


class BatchAccepted(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    batch_id: Annotated[str, Field(max_length=128, min_length=1)]
    task_id: Annotated[str, Field(max_length=128, min_length=1)]
    items: list[BatchItemReceipt]
    poll_after_ms: Annotated[int, Field(ge=1000)]


class CallSummary(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    call_id: Annotated[str, Field(max_length=128, min_length=1)]
    status: Literal[
        "queued",
        "waiting_conditions",
        "scheduled",
        "in_progress",
        "awaiting_reschedule",
        "reconciling",
        "ended",
        "cancelled",
    ]
    stop_status: Literal["none", "requested", "confirmed", "failed", "unknown"]
    reason: Reason | None
    attempt_count: Annotated[int, Field(ge=0)]
    provenance: Provenance


class ReportSummary(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    report_id: Annotated[str, Field(max_length=128, min_length=1)]
    application_id: Annotated[str, Field(max_length=128, min_length=1)]
    job_id: Annotated[str, Field(max_length=128, min_length=1)]
    version: Annotated[int, Field(ge=1)]
    revision: Annotated[int, Field(ge=1)]
    status: Literal["draft", "pending_review", "rejected", "approved", "expired"]
    artifact_ref: ArtifactRef
    provenance: Provenance
    created_at: AwareDatetime


class DisplayName(RootModel[str]):
    root: Annotated[str, Field(max_length=100, min_length=1)]


class CandidateProfile(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    display_name: DisplayName | None
    current_role: str | None
    experience_text: str | None
    education_text: str | None


class ApplicationSummary(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    id: Annotated[str, Field(max_length=128, min_length=1)]
    candidate_id: Annotated[str, Field(max_length=128, min_length=1)]
    talent_id: str | None = None
    routing: dict[str, Any] = Field(default_factory=dict)
    job_id: Annotated[str, Field(max_length=128, min_length=1)]
    workflow_id: Annotated[str, Field(max_length=128, min_length=1)]
    revision: Annotated[int, Field(ge=1)]
    candidate: CandidateProfile
    stage: Literal[
        "matched",
        "intake",
        "research",
        "screening",
        "outreach",
        "extraction",
        "evaluation",
        "recommendation",
        "finished",
    ]
    screening_result: Literal["pending", "passed", "unknown", "rejected", "manual_review"]
    evaluation_result: Literal[
        "pending", "insufficient", "recommended", "rejected", "manual_review"
    ]
    summary: str | None
    gaps: list[str]
    waiting_reason: Reason | None
    rule_pack_ref: RulePackRef
    call_summary: CallSummary | None
    report_summary: ReportSummary | None
    active_task_ids: list[ActiveTaskId]
    allowed_actions: list[str]
    provenance: Provenance
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ArtifactSlot(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    type: Literal["D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "D09", "D10"]
    state: Literal["not_executed", "processing", "available", "failed", "invalidated"]
    reason: Reason | None
    artifact_ref: ArtifactRef | None


class Application(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    id: Annotated[str, Field(max_length=128, min_length=1)]
    candidate_id: Annotated[str, Field(max_length=128, min_length=1)]
    talent_id: str | None = None
    routing: dict[str, Any] = Field(default_factory=dict)
    job_id: Annotated[str, Field(max_length=128, min_length=1)]
    workflow_id: Annotated[str, Field(max_length=128, min_length=1)]
    revision: Annotated[int, Field(ge=1)]
    candidate: CandidateProfile
    stage: Literal[
        "matched",
        "intake",
        "research",
        "screening",
        "outreach",
        "extraction",
        "evaluation",
        "recommendation",
        "finished",
    ]
    screening_result: Literal["pending", "passed", "unknown", "rejected", "manual_review"]
    evaluation_result: Literal[
        "pending", "insufficient", "recommended", "rejected", "manual_review"
    ]
    summary: str | None
    gaps: list[str]
    waiting_reason: Reason | None
    rule_pack_ref: RulePackRef
    call_summary: CallSummary | None
    report_summary: ReportSummary | None
    active_task_ids: list[ActiveTaskId]
    allowed_actions: list[str]
    provenance: Provenance
    created_at: AwareDatetime
    updated_at: AwareDatetime
    artifact_slots: list[ArtifactSlot]


class ActorId(RootModel[str]):
    root: Annotated[str, Field(max_length=128, min_length=1)]


class TimelineEvent(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    id: Annotated[str, Field(max_length=128, min_length=1)]
    type: str
    title: str
    detail: str
    actor_type: Literal["user", "system", "provider"]
    actor_id: ActorId | None
    created_at: AwareDatetime
    artifact_ref: ArtifactRef | None


class Claim(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    text: str
    evidence_refs: list[EvidenceRef]
    category: Literal["E1", "E2", "E3", "U"]


class FieldValue(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    name: str
    value: str | None
    evidence_refs: list[EvidenceRef]


class ConditionResult(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    condition_id: Annotated[str, Field(max_length=128, min_length=1)]
    result: Literal["satisfied", "not_satisfied", "unknown"]
    reason: str
    evidence_refs: list[EvidenceRef]


class Question(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    question_id: Annotated[str, Field(max_length=128, min_length=1)]
    dimension_id: Annotated[str, Field(max_length=128, min_length=1)]
    text: str
    required: bool
    candidate_specific: bool
    follow_up_conditions: list[str]


class StartMs(RootModel[int]):
    root: Annotated[int, Field(ge=0)]


class EndMs(RootModel[int]):
    root: Annotated[int, Field(ge=0)]


class QuestionAnswer(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    question_id: Annotated[str, Field(max_length=128, min_length=1)]
    question: str
    answer: str | None
    follow_ups: list[str]
    start_ms: StartMs | None
    end_ms: EndMs | None
    evidence_refs: list[EvidenceRef]


class DimensionAssessment(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    dimension_id: Annotated[str, Field(max_length=128, min_length=1)]
    status: Literal["evaluated", "not_evaluated", "insufficient"]
    score: float | None
    weight: Weight | None
    reason: str
    evidence_refs: list[EvidenceRef]


class D01Content(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    fields: list[FieldValue]
    unknown_fields: list[str]
    conflicts: list[str]
    job_form: JobForm | None = None


class D02Content(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    dimensions: list[InterviewDimension]
    recommendation_policy: RecommendationPolicy | None
    confirmation_status: Literal["draft", "needs_information", "confirmed"]


class TalentProfileRef(BaseModel):
    talent_id: str
    version: int = Field(ge=1)


class D03Content(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    profile: CandidateProfile
    employment: list[Claim]
    projects: list[Claim]
    skills: list[str]
    education: list[Claim]
    claims: list[Claim]
    research_objects: list[ResearchObject] = Field(default_factory=list)
    resume_form: ResumeForm | None = None
    document_metadata: DocumentMetadata | None = None
    direction_assignments: list[DirectionAssignment] = Field(default_factory=list)
    talent_profile_ref: TalentProfileRef | None = None


class D04Content(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    subjects: list[str]
    findings: list[Claim]
    conflicts: list[str]
    gaps: list[str]
    stop_reason: Reason
    usage: Usage
    report: ResearchReport | None = None


class D05Content(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    experience_context: str
    match_signals: list[Claim]
    gaps: list[str]
    verification_questions: list[str]
    portrait: dict[str, str] | None = None
    assessment_refs: dict[str, ArtifactRef] = Field(default_factory=dict)
    form_context: dict[str, str | int | None] = Field(default_factory=dict)


class D06Content(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    conditions: list[ConditionResult]
    conclusion: Literal["pending", "passed", "unknown", "rejected", "manual_review"]
    override_of_ref: ArtifactRef | None
    screening_rubric: ScreeningRubric | None = None
    assessment: ScreeningAssessment | None = None
    score_summary: ScoreSummary | None = None


class D07Content(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    questions: list[Question]
    termination_conditions: list[str]


class D08Content(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    coverage: Literal["full", "partial"]
    qa: Annotated[list[QuestionAnswer], Field(min_length=1)]
    conflicts: list[str]
    gaps: list[str]
    call_ref: Annotated[str, Field(max_length=128, min_length=1)]


class D09Content(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    dimensions: list[DimensionAssessment]
    coverage: Literal["full", "partial"]
    conclusion: Literal["pending", "insufficient", "recommended", "rejected", "manual_review"]
    rule_pack_ref: RulePackRef


class D10Content(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    candidate_summary: str
    match_highlights: list[Claim]
    contribution_claims: list[Claim]
    job_intention: str | None
    unknowns: list[str]


class Generator(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    kind: Literal["model", "manual", "parser", "research_adapter", "voice_adapter"]
    model: str | None
    method_version: str | None


class Validation(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    passed: bool
    issues: list[ValidationIssue]


class ArtifactSummary(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    artifact_id: Annotated[str, Field(max_length=128, min_length=1)]
    type: Literal["D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "D09", "D10"]
    version: Annotated[int, Field(ge=1)]
    status: Literal["valid", "expired", "restricted"]
    job_id: Annotated[str, Field(max_length=128, min_length=1)]
    application_id: ApplicationId | None
    workflow_id: Annotated[str, Field(max_length=128, min_length=1)]
    step: str
    input_refs: list[InputRef]
    rule_pack_ref: RulePackRef | None
    evidence_refs: list[EvidenceRef]
    provenance: Provenance
    generated_at: AwareDatetime
    generator: Generator
    unknowns: list[str]
    validation: Validation
    correction_of_ref: ArtifactRef | None
    superseded_by_ref: ArtifactRef | None


class D01Artifact(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    artifact_id: Annotated[str, Field(max_length=128, min_length=1)]
    type: Literal["D01"]
    version: Annotated[int, Field(ge=1)]
    status: Literal["valid", "expired", "restricted"]
    job_id: Annotated[str, Field(max_length=128, min_length=1)]
    application_id: ApplicationId | None
    workflow_id: Annotated[str, Field(max_length=128, min_length=1)]
    step: str
    input_refs: list[InputRef]
    rule_pack_ref: RulePackRef | None
    evidence_refs: list[EvidenceRef]
    provenance: Provenance
    generated_at: AwareDatetime
    generator: Generator
    unknowns: list[str]
    validation: Validation
    correction_of_ref: ArtifactRef | None
    superseded_by_ref: ArtifactRef | None
    content_markdown: str
    structured_content: D01Content


class D02Artifact(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    artifact_id: Annotated[str, Field(max_length=128, min_length=1)]
    type: Literal["D02"]
    version: Annotated[int, Field(ge=1)]
    status: Literal["valid", "expired", "restricted"]
    job_id: Annotated[str, Field(max_length=128, min_length=1)]
    application_id: ApplicationId | None
    workflow_id: Annotated[str, Field(max_length=128, min_length=1)]
    step: str
    input_refs: list[InputRef]
    rule_pack_ref: RulePackRef | None
    evidence_refs: list[EvidenceRef]
    provenance: Provenance
    generated_at: AwareDatetime
    generator: Generator
    unknowns: list[str]
    validation: Validation
    correction_of_ref: ArtifactRef | None
    superseded_by_ref: ArtifactRef | None
    content_markdown: str
    structured_content: D02Content


class D03Artifact(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    artifact_id: Annotated[str, Field(max_length=128, min_length=1)]
    type: Literal["D03"]
    version: Annotated[int, Field(ge=1)]
    status: Literal["valid", "expired", "restricted"]
    job_id: Annotated[str, Field(max_length=128, min_length=1)]
    application_id: ApplicationId | None
    workflow_id: Annotated[str, Field(max_length=128, min_length=1)]
    step: str
    input_refs: list[InputRef]
    rule_pack_ref: RulePackRef | None
    evidence_refs: list[EvidenceRef]
    provenance: Provenance
    generated_at: AwareDatetime
    generator: Generator
    unknowns: list[str]
    validation: Validation
    correction_of_ref: ArtifactRef | None
    superseded_by_ref: ArtifactRef | None
    content_markdown: str
    structured_content: D03Content


class D04Artifact(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    artifact_id: Annotated[str, Field(max_length=128, min_length=1)]
    type: Literal["D04"]
    version: Annotated[int, Field(ge=1)]
    status: Literal["valid", "expired", "restricted"]
    job_id: Annotated[str, Field(max_length=128, min_length=1)]
    application_id: ApplicationId | None
    workflow_id: Annotated[str, Field(max_length=128, min_length=1)]
    step: str
    input_refs: list[InputRef]
    rule_pack_ref: RulePackRef | None
    evidence_refs: list[EvidenceRef]
    provenance: Provenance
    generated_at: AwareDatetime
    generator: Generator
    unknowns: list[str]
    validation: Validation
    correction_of_ref: ArtifactRef | None
    superseded_by_ref: ArtifactRef | None
    content_markdown: str
    structured_content: D04Content


class D05Artifact(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    artifact_id: Annotated[str, Field(max_length=128, min_length=1)]
    type: Literal["D05"]
    version: Annotated[int, Field(ge=1)]
    status: Literal["valid", "expired", "restricted"]
    job_id: Annotated[str, Field(max_length=128, min_length=1)]
    application_id: ApplicationId | None
    workflow_id: Annotated[str, Field(max_length=128, min_length=1)]
    step: str
    input_refs: list[InputRef]
    rule_pack_ref: RulePackRef | None
    evidence_refs: list[EvidenceRef]
    provenance: Provenance
    generated_at: AwareDatetime
    generator: Generator
    unknowns: list[str]
    validation: Validation
    correction_of_ref: ArtifactRef | None
    superseded_by_ref: ArtifactRef | None
    content_markdown: str
    structured_content: D05Content


class D06Artifact(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    artifact_id: Annotated[str, Field(max_length=128, min_length=1)]
    type: Literal["D06"]
    version: Annotated[int, Field(ge=1)]
    status: Literal["valid", "expired", "restricted"]
    job_id: Annotated[str, Field(max_length=128, min_length=1)]
    application_id: ApplicationId | None
    workflow_id: Annotated[str, Field(max_length=128, min_length=1)]
    step: str
    input_refs: list[InputRef]
    rule_pack_ref: RulePackRef | None
    evidence_refs: list[EvidenceRef]
    provenance: Provenance
    generated_at: AwareDatetime
    generator: Generator
    unknowns: list[str]
    validation: Validation
    correction_of_ref: ArtifactRef | None
    superseded_by_ref: ArtifactRef | None
    content_markdown: str
    structured_content: D06Content


class D07Artifact(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    artifact_id: Annotated[str, Field(max_length=128, min_length=1)]
    type: Literal["D07"]
    version: Annotated[int, Field(ge=1)]
    status: Literal["valid", "expired", "restricted"]
    job_id: Annotated[str, Field(max_length=128, min_length=1)]
    application_id: ApplicationId | None
    workflow_id: Annotated[str, Field(max_length=128, min_length=1)]
    step: str
    input_refs: list[InputRef]
    rule_pack_ref: RulePackRef | None
    evidence_refs: list[EvidenceRef]
    provenance: Provenance
    generated_at: AwareDatetime
    generator: Generator
    unknowns: list[str]
    validation: Validation
    correction_of_ref: ArtifactRef | None
    superseded_by_ref: ArtifactRef | None
    content_markdown: str
    structured_content: D07Content


class D08Artifact(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    artifact_id: Annotated[str, Field(max_length=128, min_length=1)]
    type: Literal["D08"]
    version: Annotated[int, Field(ge=1)]
    status: Literal["valid", "expired", "restricted"]
    job_id: Annotated[str, Field(max_length=128, min_length=1)]
    application_id: ApplicationId | None
    workflow_id: Annotated[str, Field(max_length=128, min_length=1)]
    step: str
    input_refs: list[InputRef]
    rule_pack_ref: RulePackRef | None
    evidence_refs: list[EvidenceRef]
    provenance: Provenance
    generated_at: AwareDatetime
    generator: Generator
    unknowns: list[str]
    validation: Validation
    correction_of_ref: ArtifactRef | None
    superseded_by_ref: ArtifactRef | None
    content_markdown: str
    structured_content: D08Content


class D09Artifact(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    artifact_id: Annotated[str, Field(max_length=128, min_length=1)]
    type: Literal["D09"]
    version: Annotated[int, Field(ge=1)]
    status: Literal["valid", "expired", "restricted"]
    job_id: Annotated[str, Field(max_length=128, min_length=1)]
    application_id: ApplicationId | None
    workflow_id: Annotated[str, Field(max_length=128, min_length=1)]
    step: str
    input_refs: list[InputRef]
    rule_pack_ref: RulePackRef | None
    evidence_refs: list[EvidenceRef]
    provenance: Provenance
    generated_at: AwareDatetime
    generator: Generator
    unknowns: list[str]
    validation: Validation
    correction_of_ref: ArtifactRef | None
    superseded_by_ref: ArtifactRef | None
    content_markdown: str
    structured_content: D09Content


class D10Artifact(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    artifact_id: Annotated[str, Field(max_length=128, min_length=1)]
    type: Literal["D10"]
    version: Annotated[int, Field(ge=1)]
    status: Literal["valid", "expired", "restricted"]
    job_id: Annotated[str, Field(max_length=128, min_length=1)]
    application_id: ApplicationId | None
    workflow_id: Annotated[str, Field(max_length=128, min_length=1)]
    step: str
    input_refs: list[InputRef]
    rule_pack_ref: RulePackRef | None
    evidence_refs: list[EvidenceRef]
    provenance: Provenance
    generated_at: AwareDatetime
    generator: Generator
    unknowns: list[str]
    validation: Validation
    correction_of_ref: ArtifactRef | None
    superseded_by_ref: ArtifactRef | None
    content_markdown: str
    structured_content: D10Content


class Artifact(
    RootModel[
        D01Artifact
        | D02Artifact
        | D03Artifact
        | D04Artifact
        | D05Artifact
        | D06Artifact
        | D07Artifact
        | D08Artifact
        | D09Artifact
        | D10Artifact
    ]
):
    root: Annotated[
        D01Artifact
        | D02Artifact
        | D03Artifact
        | D04Artifact
        | D05Artifact
        | D06Artifact
        | D07Artifact
        | D08Artifact
        | D09Artifact
        | D10Artifact,
        Field(discriminator="type"),
    ]


class Page(RootModel[int]):
    root: Annotated[int, Field(ge=1)]


class EvidenceLocation(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    page: Page | None
    section: str | None
    start_ms: StartMs | None
    end_ms: EndMs | None


class PublicUrl(RootModel[AnyUrl]):
    root: AnyUrl


class Evidence(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    evidence_id: Annotated[str, Field(max_length=128, min_length=1)]
    version: Annotated[int, Field(ge=1)]
    subject_type: Literal["job", "candidate", "company", "project", "application"]
    subject_id: Annotated[str, Field(max_length=128, min_length=1)]
    category: Literal["E1", "E2", "E3", "U"] | None
    source_type: Literal[
        "public_web",
        "resume",
        "call_transcript",
        "model_analysis",
        "job_material",
        "manual_revision",
        "missing_information",
    ]
    title: str
    quote: str | None
    original_material_ref: FileRef | None
    location: EvidenceLocation
    public_url: PublicUrl | None
    source_date: AwareDatetime | None
    retrieved_at: AwareDatetime
    status: Literal["valid", "expired", "restricted"]
    corrects_ref: EvidenceRef | None
    provenance: Provenance


class ExistingCallId(RootModel[str]):
    root: Annotated[str, Field(max_length=128, min_length=1)]


class ScreeningReviewResult(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    application_id: Annotated[str, Field(max_length=128, min_length=1)]
    original_ref: ArtifactRef
    new_ref: ArtifactRef
    result: Literal["pending", "passed", "unknown", "rejected", "manual_review"]
    existing_call_id: ExistingCallId | None
    reviewer_id: Annotated[str, Field(max_length=128, min_length=1)]
    reviewed_at: AwareDatetime


class BlockedTaskId(RootModel[str]):
    root: Annotated[str, Field(max_length=128, min_length=1)]


class AffectedDeliveryId(RootModel[str]):
    root: Annotated[str, Field(max_length=128, min_length=1)]


class CorrectionResult(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    correction_id: Annotated[str, Field(max_length=128, min_length=1)]
    application_id: Annotated[str, Field(max_length=128, min_length=1)]
    new_artifact_ref: ArtifactRef
    invalidated_artifact_refs: list[ArtifactRef]
    blocked_task_ids: list[BlockedTaskId]
    affected_delivery_ids: list[AffectedDeliveryId]
    requires_recompute: bool
    created_at: AwareDatetime


class JobPage(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    items: list[Job]
    total: Annotated[int, Field(ge=0)]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]


class RulePackPage(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    items: list[RulePack]
    total: Annotated[int, Field(ge=0)]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]


class TodoPage(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    items: list[Todo]
    total: Annotated[int, Field(ge=0)]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]


class BatchItemPage(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    items: list[BatchItem]
    total: Annotated[int, Field(ge=0)]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]


class ApplicationPage(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    items: list[ApplicationSummary]
    total: Annotated[int, Field(ge=0)]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]


class ArtifactPage(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    items: list[ArtifactSummary]
    total: Annotated[int, Field(ge=0)]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]


class TimelinePage(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    items: list[TimelineEvent]
    total: Annotated[int, Field(ge=0)]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]


for _model in [
    ActiveTaskId,
    ActorId,
    ActualCost,
    AffectedDeliveryId,
    Application,
    ApplicationId,
    ApplicationPage,
    ApplicationSummary,
    Artifact,
    ArtifactPage,
    ArtifactRef,
    ArtifactSlot,
    ArtifactSummary,
    Batch,
    BatchAccepted,
    BatchItem,
    BatchItemPage,
    BatchItemReceipt,
    BlockedTaskId,
    Budget,
    CallSeconds,
    CallSummary,
    CandidateId,
    CandidateProfile,
    Capabilities,
    Claim,
    ConditionResult,
    CorrectionResult,
    Counts,
    Counts1,
    D01Artifact,
    D01Content,
    D02Artifact,
    D02Content,
    D03Artifact,
    D03Content,
    D04Artifact,
    D04Content,
    D05Artifact,
    D05Content,
    D06Artifact,
    D06Content,
    D07Artifact,
    D07Content,
    D08Artifact,
    D08Content,
    D09Artifact,
    D09Content,
    D10Artifact,
    D10Content,
    DimensionAssessment,
    DisplayName,
    DuplicateOfItemId,
    EndMs,
    Error,
    Estimated,
    EstimatedCost,
    Evidence,
    EvidenceLocation,
    EvidenceRef,
    ExistingCallId,
    FieldValue,
    FileRef,
    Generator,
    ImportLimits,
    InputRef,
    Job,
    JobId,
    JobPage,
    Limit,
    Location,
    Organization,
    Page,
    PollAfterMs,
    Provenance,
    PublicUrl,
    Question,
    QuestionAnswer,
    Reason,
    Remaining,
    ReplacesItemId,
    ReportSummary,
    Reserved,
    RuleDraft,
    RulePack,
    RulePackPage,
    RulePackRef,
    Salary,
    ScreeningReviewResult,
    SearchCount,
    Session,
    Settled,
    SourceMode,
    StageSources,
    StartMs,
    Task,
    TaskAccepted,
    TaskId,
    TimelineEvent,
    TimelinePage,
    Todo,
    TodoPage,
    Tokens,
    Usage,
    User,
    Validation,
    ValidationIssue,
    Weight,
    WorkspaceSummary,
]:
    _model.model_rebuild()
