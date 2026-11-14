"""Versioned evaluation configuration and deterministic evidence gates."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Dimension(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    weight: float = Field(gt=0, le=1)
    required_evidence: str = Field(min_length=1)
    scoring_anchors: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_anchors(self):
        if self.scoring_anchors and set(self.scoring_anchors) != {str(i) for i in range(6)}:
            raise ValueError("Scoring anchors must describe every score from zero to five")
        if any(not text.strip() for text in self.scoring_anchors.values()):
            raise ValueError("Scoring anchors cannot be empty")
        return self


class EvaluationTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    version: int = Field(ge=1)
    status: Literal["demo", "approved"]
    dimensions: list[Dimension] = Field(min_length=1)
    threshold: float = Field(ge=0, le=5)
    report_template_version: int = Field(ge=1)

    @model_validator(mode="after")
    def check_dimensions(self):
        if len({dimension.id for dimension in self.dimensions}) != len(self.dimensions):
            raise ValueError("Duplicate dimensions")
        if abs(sum(dimension.weight for dimension in self.dimensions) - 1) > 0.00001:
            raise ValueError("Weights must sum to one")
        if self.status == "approved" and any(not d.scoring_anchors for d in self.dimensions):
            raise ValueError("Approved evaluation requires scoring anchors")
        return self


class EvidenceAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dimension_id: str
    score: float | None = Field(default=None, ge=0, le=5)
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str


def validate_evaluation(
    template: EvaluationTemplate,
    assessments: list[EvidenceAssessment],
    answers: dict[str, str],
    *,
    fixture_only: bool,
):
    if template.status == "demo" and not fixture_only:
        raise ValueError("Demo rules cannot evaluate real candidates")
    expected = {dimension.id for dimension in template.dimensions}
    if {item.dimension_id for item in assessments} != expected or len(assessments) != len(expected):
        raise ValueError("Exactly one assessment per configured dimension is required")
    by_id = {item.dimension_id: item for item in assessments}
    dimensions = []
    for dimension in template.dimensions:
        item = by_id[dimension.id]
        if any(
            evidence_id not in answers or not answers[evidence_id].strip()
            for evidence_id in item.evidence_ids
        ):
            raise ValueError("Unknown or empty answer evidence")
        score = item.score if item.evidence_ids else None
        dimensions.append(
            {
                **item.model_dump(),
                "score": score,
                "status": "evaluated" if score is not None else "not_evaluated",
            }
        )
    complete = all(item["score"] is not None for item in dimensions)
    total = sum(by_id[d.id].score * d.weight for d in template.dimensions) if complete else None
    return {
        "dimensions": dimensions,
        "score": total,
        "conclusion": (
            "insufficient"
            if total is None
            else "recommended"
            if total >= template.threshold
            else "rejected"
        ),
        "template_ref": {"id": template.id, "version": template.version},
        "demo_rules": template.status == "demo",
    }
