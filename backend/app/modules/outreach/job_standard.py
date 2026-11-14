"""A02 ten-point job standard contract, separate from legacy demo evaluation."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StandardDimension(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    indicators: str = Field(min_length=1)
    weight_percent: Decimal = Field(gt=0, le=100)
    anchors: dict[str, str]
    source_refs: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_anchors(self):
        if set(self.anchors) != {"1-2", "3-4", "5-6", "7-8", "9-10"}:
            raise ValueError("Five ten-point score bands required")
        if any(not value.strip() for value in self.anchors.values()):
            raise ValueError("Empty score anchor")
        return self


class JobInterviewStandard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal["a02.v1"] = "a02.v1"
    job_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    status: Literal["draft", "confirmed"] = "draft"
    confirmed_by: str | None = None
    dimensions: list[StandardDimension] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_weights(self):
        if len({d.id for d in self.dimensions}) != len(self.dimensions):
            raise ValueError("Duplicate dimensions")
        if sum((d.weight_percent for d in self.dimensions), Decimal(0)) != 100:
            raise ValueError("Weights must sum to 100 percent")
        if self.status == "confirmed" and not (self.confirmed_by or "").strip():
            raise ValueError("Explicit confirmation actor required")
        return self


def calculate_standard_score(standard: JobInterviewStandard, scores: dict[str, int | None]):
    if standard.status != "confirmed":
        raise ValueError("STANDARD_CONFIRMATION_REQUIRED")
    if set(scores) != {d.id for d in standard.dimensions}:
        raise ValueError("Exactly one result per dimension required")
    covered = Decimal(0)
    total = Decimal(0)
    rows = []
    for dimension in standard.dimensions:
        score = scores[dimension.id]
        if score is not None and (
            isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 10
        ):
            raise ValueError("Score must be integer 1 through 10 or unevaluated")
        weighted = None if score is None else Decimal(score) / 10 * dimension.weight_percent
        if weighted is not None:
            covered += dimension.weight_percent
            total += weighted
        rows.append(
            {
                "dimension_id": dimension.id,
                "score": score,
                "weighted_score": weighted,
                "status": "not_evaluated" if score is None else "evaluated",
            }
        )
    return {
        "dimensions": rows,
        "scored_weight_percent": covered,
        "total_score": total if covered == 100 else None,
        "score_scale": "1-10",
        "total_scale": 100,
    }
