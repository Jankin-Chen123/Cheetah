"""Versioned evaluation configuration and deterministic evidence gates."""

from decimal import Decimal
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
        if self.scoring_anchors and set(self.scoring_anchors) not in (
            {str(i) for i in range(6)},
            {"1-2", "3-4", "5-6", "7-8", "9-10"},
        ):
            raise ValueError("Scoring anchors must describe the complete score scale")
        if any(not text.strip() for text in self.scoring_anchors.values()):
            raise ValueError("Scoring anchors cannot be empty")
        return self


class EvaluationTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    version: int = Field(ge=1)
    status: Literal["demo", "approved"]
    dimensions: list[Dimension] = Field(min_length=1)
    threshold: float = Field(ge=0, le=10)
    report_template_version: int = Field(ge=1)
    score_scale: Literal["0-5", "1-10"] = "0-5"

    @model_validator(mode="after")
    def check_dimensions(self):
        if self.threshold > (5 if self.score_scale == "0-5" else 10):
            raise ValueError("Threshold exceeds score scale")
        expected_anchors = (
            {str(i) for i in range(6)}
            if self.score_scale == "0-5"
            else {"1-2", "3-4", "5-6", "7-8", "9-10"}
        )
        if any(
            d.scoring_anchors and set(d.scoring_anchors) != expected_anchors
            for d in self.dimensions
        ):
            raise ValueError("Scoring anchors do not match configured scale")
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
    score: float | None = Field(default=None, ge=0, le=10)
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
        if item.score is not None and (
            (template.score_scale == "0-5" and item.score > 5)
            or (template.score_scale == "1-10" and (item.score < 1 or not item.score.is_integer()))
        ):
            raise ValueError("Score outside configured scale")
        if any(
            evidence_id not in answers or not answers[evidence_id].strip()
            for evidence_id in item.evidence_ids
        ):
            raise ValueError("Unknown or empty answer evidence")
        score = item.score if item.evidence_ids else None
        weight_percent = Decimal(str(dimension.weight)) * 100
        weighted = (
            None
            if score is None
            else Decimal(str(score))
            / (10 if template.score_scale == "1-10" else 5)
            * weight_percent
        )
        dimensions.append(
            {
                **item.model_dump(),
                "score": score,
                "label": dimension.label,
                "indicators": dimension.required_evidence,
                "scoring_anchors": dimension.scoring_anchors,
                "weight_percent": float(weight_percent),
                "weighted_score": float(weighted) if weighted is not None else None,
                "status": "evaluated" if score is not None else "not_evaluated",
            }
        )
    complete = all(item["score"] is not None for item in dimensions)
    total = sum(by_id[d.id].score * d.weight for d in template.dimensions) if complete else None
    return {
        "dimensions": dimensions,
        "score": total,
        "score_scale": template.score_scale,
        "total_scale": 100,
        "total_score": (
            float(sum(Decimal(str(row["weighted_score"])) for row in dimensions))
            if complete
            else None
        ),
        "scored_weight_percent": float(
            sum(
                Decimal(str(row["weight_percent"]))
                for row in dimensions
                if row["score"] is not None
            )
        ),
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
