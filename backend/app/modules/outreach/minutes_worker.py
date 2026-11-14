"""Version-checked D08 execution with inference outside transactions."""

from sqlalchemy.orm import Session

from app.integrations.bailian import ModelUnavailable, generate_json
from app.modules.outreach.budget import reserve_model_request
from app.modules.outreach.minutes import Minutes, generate_minutes
from app.modules.outreach.models import ModelStep, OutreachCase
from app.modules.outreach.steps import claim_step, finish_step, result_still_current


def execute_minutes(engine, settings, task_id):
    with Session(engine) as session, session.begin():
        task = session.get(ModelStep, task_id)
        if task is None or task.step != "D08":
            raise ValueError("D08_TASK_REQUIRED")
        if claim_step(session, task_id) is None:
            return
        case = session.get(OutreachCase, task.case_id)
        answers = case.session_data.get("answers", [])
        if not answers:
            finish_step(task, error_code="NO_INTERVIEW_EVIDENCE")
            return
        try:
            reserve_model_request(case, settings, "D08")
        except ModelUnavailable as error:
            finish_step(task, error_code=str(error))
            return
    try:
        result = generate_json(
            settings,
            "Extract Chinese minutes with exact answer quotes.",
            {"schema": Minutes.model_json_schema(), "answers": answers},
        )
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
            artifact = generate_minutes(session, case, settings, model_result=result)
        except ValueError:
            finish_step(task, error_code="MODEL_OUTPUT_INVALID")
            return
        finish_step(task, result_ref={"id": artifact.id, "version": artifact.version})
