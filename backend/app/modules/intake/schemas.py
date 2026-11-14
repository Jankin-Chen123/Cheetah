from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.contracts import ArtifactRef, EvidenceRef, RulePackRef
from app.modules.intake.form_contracts import Anchors, JobForm, ResumeForm, ScreeningRubric


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class CreateJobInput(Input):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    company: str | None = Field(default=None, min_length=1, max_length=100)
    location: str | None = Field(default=None, max_length=100)
    salary: str | None = Field(default=None, max_length=100)
    material_text: str = Field(min_length=1, max_length=30000)


class UpdateJobInput(Input):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=100)
    status: Literal["active", "paused", "archived"] | None = None


class AnalyzeJobInput(Input):
    expected_revision: int = Field(ge=1)
    execution_mode: Literal["live", "mock"]


class Predicate(Input):
    field: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    operator: Literal["equals", "contains", "gte"]
    expected: str | float

    @model_validator(mode="after")
    def numeric_expected(self):
        if self.operator == "gte" and not isinstance(self.expected, (int, float)):
            raise ValueError("gte requires numeric expected")
        return self


class ScreeningCondition(Input):
    id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=500)
    required_evidence: list[str] = Field(default_factory=list, max_length=10)
    evidence_sources: list[Literal["resume", "manual_revision", "public_web"]] = Field(
        default_factory=list, max_length=3
    )
    unknown_action: Literal["needs_information"] = "needs_information"
    mismatch_action: Literal["reject", "manual_review"] = "reject"
    predicate: Predicate | None = None


class InterviewDimension(Input):
    id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=200)
    rubric: str = Field(min_length=1, max_length=3000)
    weight: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    required_evidence: list[str] = Field(default_factory=list, max_length=10)
    missing_action: Literal["not_evaluated"] = "not_evaluated"
    anchors: Anchors | None = None
    source_quotes: list[str] = Field(default_factory=list, max_length=20)


class RecommendationPolicy(Input):
    required_dimension_ids: list[str] = Field(max_length=30)
    decision_method: Literal["rubric", "weighted_score"]
    threshold: float | None = Field(default=None, allow_inf_nan=False)
    manual_review_conditions: list[str] = Field(default_factory=list, max_length=30)


class ConfigRef(Input):
    config_id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)


class RuleContent(Input):
    screening_text: str = Field(default="", max_length=5000)
    interview_text: str = Field(default="", max_length=5000)
    recommendation_text: str = Field(default="", max_length=5000)
    screening_conditions: list[ScreeningCondition] = Field(default_factory=list, max_length=30)
    interview_dimensions: list[InterviewDimension] = Field(default_factory=list)
    recommendation_policy: RecommendationPolicy | None = None
    research_config_ref: ConfigRef | None = None
    phone_config_ref: ConfigRef | None = None
    method_config_ref: ConfigRef | None = None
    screening_rubric: ScreeningRubric | None = None


class SaveRuleDraftInput(Input):
    expected_draft_revision: int = Field(ge=1)
    content: RuleContent


class PublishRulesInput(Input):
    expected_draft_revision: int = Field(ge=1)
    d01_ref: ArtifactRef
    d02_ref: ArtifactRef
    is_test_rule: bool
    confirmation_note: str = Field(min_length=1, max_length=2000)


class TextItem(Input):
    client_item_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    text: str = Field(max_length=30000)


class ResumeBatchInput(Input):
    items: list[TextItem] = Field(min_length=1, max_length=10)
    execution_mode: Literal["live", "mock"] = "live"


class RetryInput(Input):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)


class Fact(Input):
    value: str | float | None
    quote: str | None = Field(default=None, max_length=2000)
    status: Literal["stated", "unknown", "conflict"]

    @model_validator(mode="after")
    def known_fact_needs_source(self):
        if self.status == "stated" and (self.value is None or not self.quote):
            raise ValueError("A stated fact requires value and quote")
        if self.status != "stated" and self.value is not None:
            raise ValueError("Unknown or conflicting facts cannot carry a definitive value")
        return self


ResearchObjectKind = Literal[
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


class ResumeResearchObject(Input):
    object_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    kind: ResearchObjectKind
    name: Fact
    period: Fact | None = None
    parent_object_id: str | None = None
    facts: dict[str, Fact] = Field(default_factory=dict, max_length=30)


class ResumeProfile(Input):
    facts: dict[str, Fact] = Field(
        max_length=100,
        description=(
            "Use canonical keys name, current_role, years_experience, education, skills, employer, "
            "employment_period, project and project_period when present. Preserve unknown/conflict "
            "rather than guessing. Include other predicate fields only with exact quotes."
        ),
    )
    unknown_fields: list[str] = Field(default_factory=list, max_length=100)
    resume_form: ResumeForm | None = None
    research_objects: list[ResumeResearchObject] = Field(
        default_factory=list,
        max_length=100,
        description=(
            "Extract EVERY stated company, project, award, paper, patent, copyright, open-source "
            "work and certification. One object per record, stable unique object_id, "
            "original name/period and exact quotes. Company: description, industry, products, "
            "location, role, contribution, metrics, website. Project: company, goal, complexity, "
            "outcomes, role, contribution, metrics, link. Professional: official_name, organizer, "
            "year, platform, identifier, authors, ownership, status, link, contribution. "
            "Preserve explicit author_identifier, orcid, contributor_handle, certificate_number "
            "or author_url when supplied; never infer them from a name. "
            "Do not infer personal contribution from team results or invent absent types."
        ),
    )

    @model_validator(mode="after")
    def unique_research_objects(self):
        ids = [item.object_id for item in self.research_objects]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate research object IDs")
        if any(
            item.parent_object_id is not None
            and (item.parent_object_id not in ids or item.parent_object_id == item.object_id)
            for item in self.research_objects
        ):
            raise ValueError("Unknown or self-referencing parent object")
        return self


class JobAnalysis(Input):
    facts: dict[str, Fact] = Field(max_length=100)
    unknown_fields: list[str] = Field(default_factory=list, max_length=100)
    rules: RuleContent
    job_form: JobForm | None = None


class InterviewStandard(Input):
    dimensions: list[InterviewDimension] = Field(max_length=100)
    gaps: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def proposed_weights(self):
        if not self.dimensions:
            if not self.gaps:
                raise ValueError("Missing job requirements need explicit gaps")
            return self
        if len({d.id for d in self.dimensions}) != len(self.dimensions):
            raise ValueError("Duplicate interview dimensions")
        if any(d.weight is None or not d.anchors or not d.source_quotes for d in self.dimensions):
            raise ValueError("A02 needs job-specific anchors, source quotes and proposed weights")
        if abs(sum(d.weight or 0 for d in self.dimensions) - 1) > 0.00001:
            raise ValueError("A02 weights must sum to 1")
        return self


class ScreeningStandard(Input):
    rubric: ScreeningRubric | None = None
    gaps: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def explicit_missing_requirements(self):
        if self.rubric is None and not self.gaps:
            raise ValueError("Missing job requirements need explicit gaps")
        return self


class CorrectionItem(Input):
    path: str = Field(min_length=1, pattern=r"^/")
    value: Fact
    reason: str = Field(min_length=1, max_length=2000)


class CorrectionInput(Input):
    target_artifact_ref: ArtifactRef
    changes: list[CorrectionItem] = Field(min_length=1, max_length=50)
    evidence_refs: list[EvidenceRef]
    reason: str = Field(min_length=1, max_length=2000)


class RecomputeInput(RetryInput):
    correction_id: str = Field(min_length=1, max_length=64)
    target_steps: list[Literal["research", "screening"]] = Field(min_length=1, max_length=2)
    rule_pack_ref: RulePackRef


class ScreeningReviewInput(Input):
    expected_d06_ref: ArtifactRef
    result: Literal["passed", "unknown", "rejected", "manual_review"]
    reason: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[EvidenceRef] = Field(min_length=1, max_length=30)
