"""A02 ten-point job standard contract, separate from legacy demo evaluation."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.outreach.evaluation import EvaluationTemplate


def evaluation_template_from_standard(
    standard: "JobInterviewStandard", *, threshold: float, report_template_version: int
) -> EvaluationTemplate:
    """Adapt a confirmed A02 standard without changing its scale or weights."""
    if standard.status != "confirmed":
        raise ValueError("STANDARD_CONFIRMATION_REQUIRED")
    return EvaluationTemplate(
        id=f"a02:{standard.job_id}",
        version=standard.version,
        status="approved",
        score_scale="1-10",
        threshold=threshold,
        report_template_version=report_template_version,
        dimensions=[
            {
                "id": dimension.id,
                "label": dimension.label,
                "weight": float(dimension.weight_percent / 100),
                "required_evidence": dimension.indicators,
                "scoring_anchors": dimension.anchors,
            }
            for dimension in standard.dimensions
        ],
    )


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


def bind_confirmed_standard(
    session,
    case,
    standard: JobInterviewStandard,
    *,
    threshold: float,
    report_template_version: int,
    expected_revision: int,
    actor_id: str,
):
    from datetime import UTC, datetime

    from app.modules.outreach.artifacts import invalidate_downstream
    from app.modules.outreach.templates import snapshot

    if case.revision != expected_revision:
        raise ValueError("VERSION_CONFLICT")
    if standard.job_id != case.job_id:
        raise ValueError("STANDARD_JOB_MISMATCH")
    if standard.status != "confirmed":
        raise ValueError("STANDARD_CONFIRMATION_REQUIRED")
    previous = case.session_data.get("job_interview_standard")
    if previous and standard.version <= previous["standard"]["version"]:
        raise ValueError("STANDARD_VERSION_MUST_INCREASE")
    confirmed = standard.model_copy(update={"confirmed_by": actor_id})
    template = evaluation_template_from_standard(
        confirmed, threshold=threshold, report_template_version=report_template_version
    )
    data = dict(case.session_data)
    history = list(data.get("evaluation_binding_history", []))
    if data.get("evaluation_template"):
        history.append(
            {
                "evaluation_template": data["evaluation_template"],
                "job_interview_standard": previous,
            }
        )
    data.update(
        {
            "evaluation_template": snapshot(template),
            "evaluation_binding_history": history,
            "job_interview_standard": {
                "standard": confirmed.model_dump(mode="json"),
                "confirmed_at": datetime.now(UTC).isoformat(),
                "threshold": threshold,
                "report_template_version": report_template_version,
            },
        }
    )
    case.session_data = data
    # Keep original interview evidence, but preparation made for the old rubric expires.
    from sqlalchemy import select

    from app.modules.outreach.models import OutreachArtifact

    for outline in session.scalars(
        select(OutreachArtifact).where(
            OutreachArtifact.case_id == case.id,
            OutreachArtifact.type == "D07",
            OutreachArtifact.valid.is_(True),
        )
    ):
        outline.valid = False
        outline.review_status = "expired"
        outline.revision += 1
        case.session_data = {**case.session_data, "outline_requires_regeneration": True}
    invalidate_downstream(session, case, "D08")
    case.revision += 1
    return {"revision": case.revision, "standard_version": confirmed.version}
