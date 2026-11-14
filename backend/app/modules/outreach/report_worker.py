"""D09/D10 inference outside locks; current evidence is rechecked on persistence."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.bailian import ModelUnavailable, generate_json
from app.modules.outreach.budget import reserve_model_request
from app.modules.outreach.models import ModelStep, OutreachArtifact, OutreachCase
from app.modules.outreach.postprocessing_prompts import (
    EVALUATION_INSTRUCTION,
    RECOMMENDATION_INSTRUCTION,
)
from app.modules.outreach.recommendation import (
    AssessmentOutput,
    RecommendationOutput,
    generate_evaluation,
    generate_recommendation,
)
from app.modules.outreach.steps import claim_step, finish_step, result_still_current
from app.modules.outreach.templates import bind_templates


def execute_report_step(engine, settings, task_id):
    with Session(engine) as session, session.begin():
        task = session.get(ModelStep, task_id)
        if task is None or task.step not in {"D09", "D10"}:
            raise ValueError("REPORT_TASK_REQUIRED")
        if claim_step(session, task_id) is None:
            return
        case = session.get(OutreachCase, task.case_id)
        step = task.step
        upstream = session.scalar(
            select(OutreachArtifact).where(
                OutreachArtifact.case_id == case.id,
                OutreachArtifact.valid.is_(True),
                OutreachArtifact.type == ("D08" if step == "D09" else "D09"),
            )
        )
        if upstream is None or (
            step == "D10" and upstream.content.get("conclusion") != "recommended"
        ):
            finish_step(task, error_code="CURRENT_ELIGIBLE_INPUT_REQUIRED")
            return
        try:
            bound = bind_templates(case, settings, step)
        except (OSError, ValueError):
            finish_step(task, error_code="TEMPLATE_CONFIGURATION_INVALID")
            return
        if step == "D10" and bound["content"]["version"] != upstream.provenance.get(
            "template", {}
        ).get("report_template_version", 1):
            finish_step(task, error_code="REPORT_TEMPLATE_VERSION_MISMATCH")
            return
        try:
            reserve_model_request(case, settings, step)
        except ModelUnavailable as error:
            finish_step(task, error_code=str(error))
            return
        if step == "D09":
            context = {
                "schema": AssessmentOutput.model_json_schema(),
                "template": bound["content"],
                "minutes": upstream.content,
            }
            instruction = EVALUATION_INSTRUCTION
        else:
            context = {
                "schema": RecommendationOutput.model_json_schema(),
                "answers": case.session_data.get("answers", []),
                "evaluation": upstream.content,
                "report_template": bound["content"],
            }
            instruction = RECOMMENDATION_INSTRUCTION
    try:
        result = generate_json(settings, instruction, context)
        failure = None
    except ModelUnavailable as error:
        failure = str(error)
    with Session(engine) as session, session.begin():
        task = session.get(ModelStep, task_id, with_for_update=True)
        case = session.get(OutreachCase, task.case_id, with_for_update=True)
        if task.status != "running":
            return
        if not result_still_current(task, case):
            task.status = "cancelled"
            task.detail = {**task.detail, "error_code": "INPUT_VERSION_CHANGED"}
            return
        if failure:
            finish_step(task, error_code=failure)
            return
        try:
            generator = generate_evaluation if step == "D09" else generate_recommendation
            artifact = generator(session, case, settings, model_result=result)
        except ValueError:
            finish_step(task, error_code="MODEL_OUTPUT_INVALID")
            return
        finish_step(task, result_ref={"id": artifact.id, "version": artifact.version})
