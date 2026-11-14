"""Durable follow-up inference without holding a case lock during network calls."""

import time

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.integrations.bailian import ModelUnavailable, generate_json
from app.modules.outreach.budget import reserve_model_request
from app.modules.outreach.interview import (
    InterviewDecision,
    bounded_topic_decision,
    termination_reason,
    validate_decision,
)
from app.modules.outreach.knowledge import retrieve
from app.modules.outreach.models import ModelStep, OutreachArtifact, OutreachCase
from app.modules.outreach.steps import claim_step, finish_step, result_still_current


def execute_followup(engine, settings: Settings, task_id: str):
    with Session(engine) as session, session.begin():
        task = session.get(ModelStep, task_id)
        if task is None or task.step != "followup":
            raise ValueError("FOLLOWUP_TASK_REQUIRED")
        snapshot = claim_step(session, task_id)
        if snapshot is None:
            return
        case = session.get(OutreachCase, task.case_id)
        data = case.session_data
        if data.get("decision_status") != "pending" or not data.get("answers"):
            finish_step(task, error_code="NO_PENDING_ANSWER")
            return
        reason = termination_reason(
            "", len(data["answers"]), time.time() - data.get("started_at", time.time())
        )
        if reason:
            case.status = "ended"
            case.stop_status = "confirmed"
            case.session_data = {**data, "decision_status": "stopped", "termination_reason": reason}
            case.revision += 1
            finish_step(task, result_ref={"kind": "program_stop", "reason": reason})
            return
        methods = retrieve(
            session,
            {"responsibility", "results", "detail", "conflict"},
            preview=data.get("knowledge_preview", False),
            structured_only=True,
        )
        outline = (
            session.get(OutreachArtifact, data.get("outline_id"))
            if data.get("outline_id")
            else None
        )
        program_decision = bounded_topic_decision(data, outline.content if outline else {})
        if program_decision is not None:
            methods = outline.content.get("retrieved_methods", []) if outline else methods
        else:
            try:
                reserve_model_request(case, settings, "followup")
            except ModelUnavailable as error:
                finish_step(task, error_code=str(error))
                return
        context = {
            "schema": InterviewDecision.model_json_schema(),
            "dimensions": ["responsibility", "results"],
            "methods": methods,
            "answers": data["answers"],
            "upstream_content": data.get("upstream_content"),
            "outline": outline.content if outline else None,
            "prior_decisions": data.get("decisions", []),
        }
    try:
        if not methods:
            raise ModelUnavailable("KNOWLEDGE_NOT_READY")
        if program_decision is not None:
            result = {
                "content": program_decision.model_dump(),
                "model": None,
                "usage": None,
                "source_mode": "mock",
                "generator_kind": "program_topic_limit",
            }
        else:
            result = generate_json(
                settings,
                "Choose followup, clarify, next_topic or end. "
                "Ask one Chinese question grounded in actual answers and methods. "
                "Use only the supplied dimension IDs, method entry_id values and answer id values. "
                "For a non-end action include question, dimension_id and method_entry_ids. "
                "Every decision must cite the latest answer id in answer_evidence_ids. "
                "Do not repeat a question already present in answers. "
                "General methods are not industry standards. Do not invent tools, "
                "metrics or technical requirements absent from supplied job rules and answers. "
                "Ask one evidence gap at a time. If the current target is sufficiently "
                "answered, choose next_topic for an uncovered outline question; if all targets are "
                "covered or no evidence can be added, choose end. Preserve unknowns rather "
                "than repeatedly demanding unavailable evidence. Never infer personal contribution "
                "from company results or ability from emotional tone.",
                context,
            )
        decision = validate_decision(
            InterviewDecision.model_validate(result["content"]),
            methods,
            data["answers"],
            [a["question"]["question"] for a in data["answers"]],
            {"responsibility", "results"},
        )
        failure = None
    except (ModelUnavailable, ValueError) as error:
        failure = str(error) if isinstance(error, ModelUnavailable) else "MODEL_OUTPUT_INVALID"
    with Session(engine) as session, session.begin():
        task = session.get(ModelStep, task_id, with_for_update=True)
        case = session.get(OutreachCase, task.case_id, with_for_update=True)
        if task.status != "running":
            return
        if not result_still_current(task, case):
            task.status = "cancelled"
            task.detail = {**task.detail, "error_code": "INPUT_CHANGED_OR_STOPPED"}
            return
        if failure:
            finish_step(task, error_code=failure)
            return
        history = [
            *case.session_data.get("decisions", []),
            {
                **decision.model_dump(),
                "methods": methods,
                "model": result["model"],
                "usage": result["usage"],
                "source_mode": result.get("source_mode", "live"),
                "generator_kind": result.get("generator_kind", "model"),
            },
        ]
        case.session_data = {
            **case.session_data,
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
        finish_step(task, result_ref={"kind": "decision", "sequence": len(history)})
