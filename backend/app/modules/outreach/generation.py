"""Interview generation from bounded retrieved methods and immutable inputs."""

import time

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.integrations.bailian import ModelUnavailable, generate_json
from app.modules.outreach.artifacts import save_artifact
from app.modules.outreach.budget import reserve_model_request
from app.modules.outreach.handoff import question_execution_ref
from app.modules.outreach.interview import (
    InterviewDecision,
    Outline,
    termination_reason,
    validate_decision,
    validate_outline,
    validate_question_cards,
)
from app.modules.outreach.knowledge import retrieve
from app.modules.outreach.models import OutreachArtifact, OutreachCase
from app.modules.outreach.outline_inputs import outline_dimensions, outline_handoff, outline_inputs
from app.modules.outreach.outline_prompts import OUTLINE_INSTRUCTION, PROMPT_VERSION
from app.modules.outreach.outline_review import review_and_revise_outline
from app.modules.outreach.provenance import inherited_provenance
from app.modules.outreach.worker import reusable_outline


def generate_outline(session: Session, case: OutreachCase, settings: Settings, *, preview: bool):
    if case.stop_status != "none" or case.status in {"ended", "cancelled"}:
        raise ValueError("INTERVIEW_STOPPED")
    upstream = outline_inputs(case)
    dimensions = outline_dimensions(case)
    dimension_ids = {dimension["id"] for dimension in dimensions}
    methods = retrieve(
        session, {"responsibility", "results", "detail"}, preview=preview, structured_only=True
    )
    outline_id = case.session_data.get("outline_id")
    existing = session.get(OutreachArtifact, outline_id) if outline_id else None
    if reusable_outline(case, existing, methods, preview=preview):
        return existing
    if case.session_data.get("answers"):
        raise ValueError("INTERVIEW_EXECUTION_ALREADY_STARTED")
    result = generate_json(
        settings,
        OUTLINE_INSTRUCTION,
        {
            "schema": Outline.model_json_schema(),
            "upstream": case.snapshot,
            "upstream_content": upstream,
            "methods": methods,
            "dimensions": sorted(dimension_ids),
            "confirmed_dimension_details": dimensions,
        },
    )
    outline = validate_outline(Outline.model_validate(result["content"]), methods, dimension_ids)
    if case.session_data.get("job_interview_standard"):
        validate_question_cards(outline, dimension_ids, case.snapshot["artifact_refs"])
        reserve_model_request(case, settings, "D07_quality_review")

        def reserve_revision():
            reserve_model_request(case, settings, "D07_wording_revision")
            reserve_model_request(case, settings, "D07_revision_review")

        outline, quality_review = review_and_revise_outline(settings, outline, reserve_revision)
    else:
        quality_review = None
    artifact = save_artifact(
        session,
        case,
        "D07",
        {
            **outline.model_dump(),
            **outline_handoff(case, outline, dimensions, preview=preview),
            "retrieved_methods": methods,
            "knowledge_preview": preview,
            "dimension_ids": sorted(dimension_ids),
            "dimension_details": dimensions,
        },
        {
            "source_mode": "live",
            **inherited_provenance(case),
            "agent_id": "A10",
            "prompt_version": PROMPT_VERSION,
            "job_interview_standard": case.session_data.get("job_interview_standard"),
            "quality_review": quality_review,
            "model": result["model"],
            "usage": result["usage"],
        },
        [
            {"kind": "artifact", "id": ref["artifact_id"], "version": ref["version"]}
            for ref in case.snapshot["artifact_refs"].values()
        ],
    )
    case.session_data = {
        **case.session_data,
        "outline_id": artifact.id,
        "outline_requires_regeneration": False,
        "current_question": {
            **outline.questions[0].model_dump(),
            "execution_ref": question_execution_ref(artifact, outline.questions[0].id),
        },
        "knowledge_preview": preview,
        "generation_status": "completed",
    }
    case.revision += 1
    return artifact


def generate_followup(session: Session, case: OutreachCase, settings: Settings):
    data = case.session_data
    if case.stop_status != "none" or case.status in {"ended", "cancelled"}:
        raise ValueError("INTERVIEW_STOPPED")
    if data.get("decision_status") != "pending" or not data.get("answers"):
        raise ValueError("NO_PENDING_ANSWER")
    latest = data["answers"][-1]
    reason = termination_reason(
        "", len(data["answers"]), time.time() - data.get("started_at", time.time())
    )
    if reason:
        case.status = "ended"
        case.stop_status = "confirmed"
        case.session_data = {**data, "decision_status": "stopped", "termination_reason": reason}
        case.revision += 1
        return InterviewDecision(action="end", reason=reason)
    dimension = latest["question"].get("dimension_id", "responsibility")
    tags = {dimension, "detail", "quantification", "conflict"}
    methods = retrieve(
        session, tags, preview=data.get("knowledge_preview", False), structured_only=True
    )
    if not methods:
        raise ModelUnavailable("KNOWLEDGE_NOT_READY")
    result = generate_json(
        settings,
        "Choose clarify, followup, next_topic or end. Ask one Chinese question. "
        "Every decision must cite the latest answer id in answer_evidence_ids. "
        "Do not repeat questions; distinguish company results from personal work. "
        "General methods are not industry standards: do not invent tools, metrics or technical "
        "requirements absent from supplied job rules and answers. Ask one evidence gap at a time. "
        "When the current target is sufficiently answered, choose next_topic for an uncovered "
        "outline target; when all targets are covered or no further evidence is available, end "
        "and preserve unknowns. Do not infer ability from emotional tone.",
        {
            "schema": InterviewDecision.model_json_schema(),
            "methods": methods,
            "answers": data["answers"],
            "upstream": case.snapshot,
            "upstream_content": data.get("upstream_content"),
            "dimensions": ["responsibility", "results"],
            "prior_decisions": data.get("decisions", []),
        },
    )
    decision = validate_decision(
        InterviewDecision.model_validate(result["content"]),
        methods,
        data["answers"],
        [answer["question"]["question"] for answer in data["answers"]],
        {"responsibility", "results"},
    )
    history = [
        *data.get("decisions", []),
        {
            **decision.model_dump(),
            "methods": methods,
            "model": result["model"],
            "usage": result["usage"],
            "source_mode": "live",
        },
    ]
    case.session_data = {
        **data,
        "decisions": history,
        "decision_status": "completed",
        "current_question": None
        if decision.action == "end"
        else {
            "id": f"followup-{len(history)}",
            "question": decision.question,
            "dimension_id": decision.dimension_id,
            "method_entry_ids": decision.method_entry_ids,
        },
    }
    if decision.action == "end":
        case.status = "ended"
        case.stop_status = "confirmed"
    case.revision += 1
    return decision
