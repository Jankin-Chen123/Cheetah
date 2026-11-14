"""One-shot durable D07 worker; external inference runs outside database transactions."""

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.integrations.bailian import ModelUnavailable, generate_json
from app.modules.outreach.artifacts import save_artifact
from app.modules.outreach.budget import reserve_model_request
from app.modules.outreach.handoff import question_execution_ref
from app.modules.outreach.interview import Outline, validate_outline, validate_question_cards
from app.modules.outreach.knowledge import retrieve
from app.modules.outreach.models import ModelStep, OutreachArtifact, OutreachCase
from app.modules.outreach.outline_inputs import (
    outline_dimensions,
    outline_handoff,
    outline_inputs,
    require_execution_outline,
)
from app.modules.outreach.outline_prompts import OUTLINE_INSTRUCTION, PROMPT_VERSION
from app.modules.outreach.outline_review import review_and_revise_outline
from app.modules.outreach.provenance import inherited_provenance
from app.modules.outreach.steps import claim_step, finish_step, result_still_current


def reusable_outline(case, outline, methods, *, preview):
    try:
        require_execution_outline(case, outline)
    except ValueError:
        return False
    return bool(
        outline is not None
        and outline.provenance.get("prompt_version") == PROMPT_VERSION
        and outline.content.get("knowledge_preview") == preview
        and outline.content.get("retrieved_methods") == methods
    )


def execute_outline(engine, settings: Settings, task_id: str):
    with Session(engine) as session, session.begin():
        task = session.get(ModelStep, task_id)
        if task is None or task.step != "D07":
            raise ValueError("D07_TASK_REQUIRED")
        snapshot = claim_step(session, task_id)
        if snapshot is None:
            return
        case = session.get(OutreachCase, task.case_id)
        preview = task.detail.get("knowledge_preview", False)
        try:
            upstream_content = outline_inputs(case)
            dimensions = outline_dimensions(case)
            dimension_ids = {dimension["id"] for dimension in dimensions}
            require_full_coverage = bool(case.session_data.get("job_interview_standard"))
            standard_binding = case.session_data.get("job_interview_standard")
        except ModelUnavailable as error:
            finish_step(task, error_code=str(error))
            return
        methods = retrieve(
            session,
            {"responsibility", "results", "detail"},
            preview=preview,
            structured_only=True,
        )
        outline_id = case.session_data.get("outline_id")
        existing = session.get(OutreachArtifact, outline_id) if outline_id else None
        if reusable_outline(case, existing, methods, preview=preview):
            finish_step(task, result_ref={"id": existing.id, "version": existing.version})
            return
        if case.session_data.get("answers"):
            finish_step(task, error_code="INTERVIEW_EXECUTION_ALREADY_STARTED")
            return
        try:
            reserve_model_request(case, settings, "D07")
            if require_full_coverage:
                reserve_model_request(case, settings, "D07_quality_review")
        except ModelUnavailable as error:
            finish_step(task, error_code=str(error))
            return
        context = {
            "schema": Outline.model_json_schema(),
            "upstream": case.snapshot,
            "upstream_content": upstream_content,
            "methods": methods,
            "dimensions": sorted(dimension_ids),
            "confirmed_dimension_details": dimensions,
        }
    output_validation_code = None
    validation_fields = []
    try:
        if not context["upstream_content"]:
            raise ModelUnavailable("INPUTS_NOT_READY")
        result = generate_json(settings, OUTLINE_INSTRUCTION, context)
        outline = validate_outline(
            Outline.model_validate(result["content"]), methods, dimension_ids
        )
        if require_full_coverage:
            validate_question_cards(outline, dimension_ids, context["upstream"]["artifact_refs"])

        def reserve_revision():
            with Session(engine) as revision_session, revision_session.begin():
                revision_task = revision_session.get(ModelStep, task_id, with_for_update=True)
                revision_case = revision_session.get(
                    OutreachCase, revision_task.case_id, with_for_update=True
                )
                if revision_task.status != "running" or not result_still_current(
                    revision_task, revision_case
                ):
                    raise ModelUnavailable("INPUT_CHANGED_OR_STOPPED")
                reserve_model_request(revision_case, settings, "D07_wording_revision")
                reserve_model_request(revision_case, settings, "D07_revision_review")

        quality_review = None
        if require_full_coverage:
            outline, quality_review = review_and_revise_outline(settings, outline, reserve_revision)
        failure = None
    except (ModelUnavailable, ValueError) as error:
        if str(error) in {"DIMENSION_COVERAGE_INCOMPLETE", "QUESTION_CARDS_INCOMPLETE"}:
            output_validation_code = str(error)
        if isinstance(error, ValidationError):
            validation_fields = [
                {"loc": list(item["loc"]), "type": item["type"]}
                for item in error.errors(include_input=False, include_url=False)[:12]
            ]
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
        if (
            case.snapshot != context["upstream"]
            or case.session_data.get("upstream_content") != context["upstream_content"]
            or case.session_data.get("job_interview_standard") != standard_binding
        ):
            finish_step(task, error_code="OUTLINE_INPUT_CHANGED_DURING_INFERENCE")
            return
        if failure:
            if validation_fields:
                task.detail = {**task.detail, "validation_fields": validation_fields}
            if output_validation_code:
                task.detail = {**task.detail, "output_validation_code": output_validation_code}
            finish_step(task, error_code=failure)
            return
        current_methods = retrieve(
            session,
            {"responsibility", "results", "detail"},
            preview=preview,
            structured_only=True,
        )
        if current_methods != methods:
            finish_step(task, error_code="KNOWLEDGE_CHANGED_DURING_INFERENCE")
            return
        artifact = save_artifact(
            session,
            case,
            "D07",
            {
                **outline.model_dump(),
                **outline_handoff(
                    case, outline, dimensions, preview=task.detail.get("knowledge_preview", False)
                ),
                "retrieved_methods": methods,
                "knowledge_preview": task.detail.get("knowledge_preview", False),
                "dimension_ids": sorted(dimension_ids),
                "dimension_details": dimensions,
                "planned_total_minutes": 35,
                "time_plan": {
                    "opening_consent": 2,
                    "competency": 26,
                    "candidate_questions": 4,
                    "closing": 3,
                },
            },
            {
                "source_mode": "live",
                **inherited_provenance(case),
                "agent_id": "A10",
                "prompt_version": PROMPT_VERSION,
                "job_interview_standard": standard_binding,
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
            "knowledge_preview": task.detail.get("knowledge_preview", False),
        }
        case.revision += 1
        finish_step(task, result_ref={"id": artifact.id, "version": artifact.version})
