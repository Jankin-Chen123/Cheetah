"""Evidence-grounded minutes; quotes must be exact substrings of actual answers."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.integrations.bailian import generate_json
from app.modules.outreach.artifacts import invalidate_downstream, save_artifact
from app.modules.outreach.models import OutreachCase
from app.modules.outreach.postprocessing_prompts import MINUTES_INSTRUCTION, PROMPT_VERSION
from app.modules.outreach.provenance import inherited_provenance


class MinuteFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str = Field(min_length=1, max_length=2000)
    answer_id: str
    quote: str = Field(min_length=1, max_length=4000)
    kind: Literal["responsibility", "results", "intention", "other"]


class Minutes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facts: list[MinuteFact] = Field(max_length=50)
    gaps: list[str] = Field(default_factory=list, max_length=30)
    conflicts: list[str] = Field(default_factory=list, max_length=30)


def validate_minutes(minutes: Minutes, answers: list[dict]):
    by_id = {answer["id"]: answer["text"] for answer in answers}
    if not by_id:
        raise ValueError("NO_INTERVIEW_EVIDENCE")
    for fact in minutes.facts:
        if (
            not fact.statement.strip()
            or not fact.quote.strip()
            or fact.answer_id not in by_id
            or fact.quote not in by_id[fact.answer_id]
        ):
            raise ValueError("UNSUPPORTED_MINUTE_QUOTE")
    return minutes


def generate_minutes(
    session: Session, case: OutreachCase, settings: Settings, *, model_result=None
):
    answers = case.session_data.get("answers", [])
    if not answers:
        raise ValueError("NO_INTERVIEW_EVIDENCE")
    result = (
        model_result
        if model_result is not None
        else generate_json(
            settings,
            MINUTES_INSTRUCTION,
            {"schema": Minutes.model_json_schema(), "answers": answers},
        )
    )
    minutes = validate_minutes(Minutes.model_validate(result["content"]), answers)
    covered = {fact.kind for fact in minutes.facts}
    coverage = "full" if {"responsibility", "results"}.issubset(covered) else "partial"
    invalidate_downstream(session, case, "D08")
    artifact = save_artifact(
        session,
        case,
        "D08",
        {**minutes.model_dump(), "qa": answers, "coverage": coverage, "call_ref": case.id},
        {
            "source_mode": "live",
            "prompt_version": PROMPT_VERSION,
            **inherited_provenance(case),
            "knowledge_preview": case.session_data.get("knowledge_preview", False),
            "model": result["model"],
            "usage": result["usage"],
        },
        [
            {"kind": "answer", "id": answer["id"], "version": answer.get("version", 1)}
            for answer in answers
        ],
    )
    case.revision += 1
    return artifact
