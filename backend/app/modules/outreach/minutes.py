"""Evidence-grounded minutes; quotes must be exact substrings of actual answers."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.integrations.bailian import generate_json
from app.modules.outreach.artifacts import invalidate_downstream, save_artifact
from app.modules.outreach.handoff import preparation_metadata, require_extraction_session
from app.modules.outreach.models import OutreachCase
from app.modules.outreach.postprocessing_prompts import MINUTES_INSTRUCTION, PROMPT_VERSION
from app.modules.outreach.provenance import inherited_provenance


class MinuteFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str = Field(min_length=1, max_length=2000)
    answer_id: str
    quote: str = Field(min_length=1, max_length=4000)
    kind: Literal["responsibility", "results", "intention", "other"]
    evidence_id: str = Field(default="", max_length=100)
    evidence_kind: Literal[
        "PAST_BEHAVIOR", "SITUATIONAL", "FACT_ONLY", "GENERAL_CLAIM", "UNKNOWN"
    ] = "UNKNOWN"
    evidence_direction: Literal["SUPPORTING", "LIMITING", "NEUTRAL", "UNCLASSIFIED", "UNKNOWN"] = (
        "UNCLASSIFIED"
    )


class IndicatorEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dimension_id: str
    indicator_ref: str
    answer_ids: list[str] = Field(default_factory=list, max_length=30)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    evidence_sufficiency: Literal["SUFFICIENT", "PARTIAL", "INSUFFICIENT"]
    sufficiency_reason: str = Field(min_length=1, max_length=2000)
    gaps: list[str] = Field(default_factory=list, max_length=20)


def extraction_indicators(case):
    binding = case.session_data.get("job_interview_standard")
    if not binding:
        return []
    from app.modules.outreach.job_standard import JobInterviewStandard

    standard = JobInterviewStandard.model_validate(binding["standard"])
    if standard.status != "confirmed" or standard.job_id != case.job_id:
        raise ValueError("STANDARD_CONFIRMATION_REQUIRED")
    return [
        {
            "dimension_id": dimension.id,
            "indicator_ref": f"dimensions[{index}].indicators",
            "indicator_text": dimension.indicators,
            "dimension_name": dimension.label,
            "weight_percent": str(dimension.weight_percent),
            "scoring_anchor_refs": {
                "standard_version": standard.version,
                "field_path": f"dimensions[{index}].anchors",
            },
        }
        for index, dimension in enumerate(standard.dimensions)
    ]


class Minutes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facts: list[MinuteFact] = Field(max_length=50)
    gaps: list[str] = Field(default_factory=list, max_length=30)
    conflicts: list[str] = Field(default_factory=list, max_length=30)
    indicator_evidence: list[IndicatorEvidence] = Field(default_factory=list, max_length=100)


def validate_minutes(minutes: Minutes, answers: list[dict]):
    by_id = {answer["id"]: answer["text"] for answer in answers}
    if not by_id:
        raise ValueError("NO_INTERVIEW_EVIDENCE")
    identifiers = [fact.evidence_id for fact in minutes.facts if fact.evidence_id]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("DUPLICATE_EVIDENCE_ID")
    for fact in minutes.facts:
        if (
            not fact.statement.strip()
            or not fact.quote.strip()
            or fact.answer_id not in by_id
            or fact.quote not in by_id[fact.answer_id]
        ):
            raise ValueError("UNSUPPORTED_MINUTE_QUOTE")
    return minutes


def validate_indicator_evidence(minutes, indicators, answers, *, require_fact_links=False):
    expected = {(row["dimension_id"], row["indicator_ref"]) for row in indicators}
    actual = [(row.dimension_id, row.indicator_ref) for row in minutes.indicator_evidence]
    if set(actual) != expected or len(actual) != len(expected):
        raise ValueError("INDICATOR_COVERAGE_INVALID")
    allowed = {answer["id"] for answer in answers if answer["text"].strip()}
    facts = {fact.evidence_id: fact for fact in minutes.facts if fact.evidence_id}
    for row in minutes.indicator_evidence:
        if (
            not set(row.answer_ids).issubset(allowed)
            or (row.evidence_sufficiency != "INSUFFICIENT" and not row.answer_ids)
            or not row.sufficiency_reason.strip()
        ):
            raise ValueError("INDICATOR_EVIDENCE_INVALID")
        if (
            len(row.evidence_ids) != len(set(row.evidence_ids))
            or any(key not in facts for key in row.evidence_ids)
            or any(facts[key].answer_id not in row.answer_ids for key in row.evidence_ids)
        ):
            raise ValueError("INDICATOR_FACT_REFERENCE_INVALID")
        if require_fact_links and (
            any(not fact.evidence_id.strip() for fact in minutes.facts)
            or set(row.answer_ids) != {facts[key].answer_id for key in row.evidence_ids}
        ):
            raise ValueError("INDICATOR_FACT_LINKS_REQUIRED")


def evidence_matrix(minutes, indicators, answers, execution_session):
    """Group explicit fact links; an answer-level reference never invents indicator relevance."""
    by_answer = {answer["id"]: answer for answer in answers}
    turns = {turn["answer_id"]: turn for turn in (execution_session or {}).get("answer_turns", [])}
    evidence_items = []
    for index, fact in enumerate(minutes.facts, 1):
        answer = by_answer[fact.answer_id]
        turn = turns.get(fact.answer_id)
        evidence_items.append(
            {
                **fact.model_dump(),
                "evidence_id": fact.evidence_id or f"legacy-EV{index}",
                "answer_version": answer.get("version", 1),
                "session_id": (execution_session or {}).get("session_id"),
                "turn_ids": [turn["turn_id"]] if turn else [],
                "source_type": turn.get("source_type", "CANDIDATE_ORAL")
                if turn
                else "ANSWER_RECORD",
                "verification_status": "MANUALLY_CORRECTED"
                if answer.get("corrected_by")
                else "SELF_REPORTED",
                "source_mode": answer.get("source_mode", "unknown"),
            }
        )
    by_evidence = {item["evidence_id"]: item for item in evidence_items}
    for item in evidence_items:
        related = [
            row for row in minutes.indicator_evidence if item["evidence_id"] in row.evidence_ids
        ]
        item["d02_dimension_ids"] = list(dict.fromkeys(row.dimension_id for row in related))
        item["indicator_refs"] = list(dict.fromkeys(row.indicator_ref for row in related))
    definitions = {(row["dimension_id"], row["indicator_ref"]): row for row in indicators}
    dimensions = {}
    for row in minutes.indicator_evidence:
        selected = [by_evidence[key] for key in row.evidence_ids]
        detail = {
            **row.model_dump(),
            "indicator_text": definitions[(row.dimension_id, row.indicator_ref)]["indicator_text"],
            "question_ids": list(
                dict.fromkeys(
                    by_answer[key].get("question", {}).get("id")
                    for key in row.answer_ids
                    if by_answer[key].get("question", {}).get("id")
                )
            ),
            "answer_turn_ids": [turns[key]["turn_id"] for key in row.answer_ids if key in turns],
            "supporting_evidence_ids": [
                item["evidence_id"]
                for item in selected
                if item["evidence_direction"] == "SUPPORTING"
            ],
            "limiting_evidence_ids": [
                item["evidence_id"] for item in selected if item["evidence_direction"] == "LIMITING"
            ],
            "situational_evidence_ids": [
                item["evidence_id"] for item in selected if item["evidence_kind"] == "SITUATIONAL"
            ],
            "neutral_evidence_ids": [
                item["evidence_id"] for item in selected if item["evidence_direction"] == "NEUTRAL"
            ],
            "fact_links_complete": bool(row.evidence_ids) or not row.answer_ids,
        }
        dimensions.setdefault(row.dimension_id, []).append(detail)
    coverage = []
    for dimension_id, rows in dimensions.items():
        definition = next(row for row in indicators if row["dimension_id"] == dimension_id)
        statuses = {row["evidence_sufficiency"] for row in rows}
        linked = all(row["fact_links_complete"] for row in rows)
        sufficiency = (
            "INSUFFICIENT"
            if not linked or "INSUFFICIENT" in statuses
            else "PARTIAL"
            if "PARTIAL" in statuses
            else "SUFFICIENT"
        )
        coverage.append(
            {
                "d02_dimension_id": dimension_id,
                "dimension_name": definition.get("dimension_name"),
                "weight_percent": definition.get("weight_percent"),
                "scoring_anchor_refs": definition.get("scoring_anchor_refs"),
                "coverage_status": (
                    "COVERED"
                    if linked and any(row["evidence_ids"] for row in rows)
                    else "PARTIAL"
                    if any(row["answer_ids"] for row in rows)
                    else "NO_EVIDENCE"
                    if any(
                        answer.get("question", {}).get("dimension_id") == dimension_id
                        for answer in answers
                    )
                    else "NOT_ASKED"
                ),
                "dimension_evidence_sufficiency": sufficiency,
                "dimension_sufficiency_reason": "；".join(row["sufficiency_reason"] for row in rows)
                + ("；旧资料缺少逐事实指标引用，需复核。" if not linked else ""),
                "indicator_evidence": rows,
                "evidence_ids": list(
                    dict.fromkeys(key for row in rows for key in row["evidence_ids"])
                ),
                "missing_evidence": list(dict.fromkeys(gap for row in rows for gap in row["gaps"])),
            }
        )
    return {"evidence_items": evidence_items, "dimension_coverage": coverage}


def generate_minutes(
    session: Session, case: OutreachCase, settings: Settings, *, model_result=None
):
    execution_session = require_extraction_session(session, case)
    answers = case.session_data.get("answers", [])
    if not answers:
        raise ValueError("NO_INTERVIEW_EVIDENCE")
    result = (
        model_result
        if model_result is not None
        else generate_json(
            settings,
            MINUTES_INSTRUCTION,
            {
                "schema": Minutes.model_json_schema(),
                "answers": answers,
                "indicators": extraction_indicators(case),
            },
        )
    )
    minutes = validate_minutes(Minutes.model_validate(result["content"]), answers)
    indicators = extraction_indicators(case)
    validate_indicator_evidence(
        minutes, indicators, answers, require_fact_links=bool(execution_session)
    )
    matrix = evidence_matrix(minutes, indicators, answers, execution_session)
    covered = {fact.kind for fact in minutes.facts}
    coverage = "full" if {"responsibility", "results"}.issubset(covered) else "partial"
    invalidate_downstream(session, case, "D08")
    artifact = save_artifact(
        session,
        case,
        "D08",
        {
            **minutes.model_dump(),
            "qa": answers,
            "coverage": coverage,
            "call_ref": case.id,
            **preparation_metadata(session, case),
            "indicator_definitions": indicators,
            "execution_session": execution_session,
            "extraction_status": "READY_FOR_A08"
            if execution_session and execution_session["status"] == "COMPLETED"
            else "PARTIAL_REVIEW",
            **matrix,
        },
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
