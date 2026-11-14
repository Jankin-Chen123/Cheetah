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
    fact_evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    matched_anchor_band: str | None = Field(default=None, max_length=20)
    anchor_rationale: str = Field(default="", max_length=4000)


def validate_evaluation(
    template: EvaluationTemplate,
    assessments: list[EvidenceAssessment],
    answers: dict[str, str],
    *,
    fixture_only: bool,
    evidence_items: list[dict] | None = None,
    require_anchor_basis: bool = False,
):
    if template.status == "demo" and not fixture_only:
        raise ValueError("Demo rules cannot evaluate real candidates")
    expected = {dimension.id for dimension in template.dimensions}
    if {item.dimension_id for item in assessments} != expected or len(assessments) != len(expected):
        raise ValueError("Exactly one assessment per configured dimension is required")
    by_id = {item.dimension_id: item for item in assessments}
    facts = {item["evidence_id"]: item for item in evidence_items or []}
    dimensions = []
    for dimension in template.dimensions:
        item = by_id[dimension.id]
        if not item.reason.strip():
            raise ValueError("ASSESSMENT_REASON_REQUIRED")
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
        if item.matched_anchor_band is not None and score is None:
            raise ValueError("UNASSESSED_ANCHOR_NOT_ALLOWED")
        if score is not None and (
            not fixture_only or require_anchor_basis or item.matched_anchor_band is not None
        ):
            expected_band = (
                f"{int(score) if int(score) % 2 else int(score) - 1}-"
                f"{int(score) + 1 if int(score) % 2 else int(score)}"
                if template.score_scale == "1-10"
                else str(int(score))
            )
            if (
                item.matched_anchor_band != expected_band
                or expected_band not in dimension.scoring_anchors
                or not item.anchor_rationale.strip()
                or not item.fact_evidence_ids
            ):
                raise ValueError("SCORING_ANCHOR_BASIS_REQUIRED")
        if len(item.fact_evidence_ids) != len(set(item.fact_evidence_ids)) or any(
            key not in facts
            or facts[key].get("answer_id") not in item.evidence_ids
            or dimension.id not in facts[key].get("d02_dimension_ids", [])
            for key in item.fact_evidence_ids
        ):
            raise ValueError("SCORING_FACT_REFERENCE_INVALID")
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
                "anchor_basis_status": (
                    "RECORDED"
                    if score is not None and item.matched_anchor_band
                    else "NOT_ASSESSED"
                    if score is None
                    else "LEGACY_NOT_RECORDED"
                ),
                "matched_anchor_text": dimension.scoring_anchors.get(item.matched_anchor_band),
            }
        )
    complete = all(item["score"] is not None for item in dimensions)
    total = (
        sum(Decimal(str(by_id[d.id].score)) * Decimal(str(d.weight)) for d in template.dimensions)
        if complete
        else None
    )
    return {
        "assessment_status": "COMPLETE" if complete else "PARTIAL",
        "summary": {
            "dimension_count": len(dimensions),
            "weight_total_percent": float(
                sum(Decimal(str(d["weight_percent"])) for d in dimensions)
            ),
            "scored_dimension_count": sum(d["score"] is not None for d in dimensions),
            "unassessed_dimension_count": sum(d["score"] is None for d in dimensions),
            "total_score_status": "CALCULABLE" if complete else "NOT_CALCULABLE",
        },
        "dimensions": dimensions,
        "score": float(total) if total is not None else None,
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
            if total >= Decimal(str(template.threshold))
            else "rejected"
        ),
        "template_ref": {"id": template.id, "version": template.version},
        "demo_rules": template.status == "demo",
    }
