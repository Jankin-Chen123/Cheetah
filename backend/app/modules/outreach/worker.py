"""One-shot durable D07 worker; external inference runs outside database transactions."""

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.integrations.bailian import ModelUnavailable, generate_json
from app.modules.outreach.artifacts import save_artifact
from app.modules.outreach.budget import reserve_model_request
from app.modules.outreach.interview import Outline, validate_outline
from app.modules.outreach.knowledge import retrieve
from app.modules.outreach.models import ModelStep, OutreachCase
from app.modules.outreach.steps import claim_step, finish_step, result_still_current


def execute_outline(engine, settings: Settings, task_id: str):
    with Session(engine) as session, session.begin():
        task = session.get(ModelStep, task_id)
        if task is None or task.step != "D07":
            raise ValueError("D07_TASK_REQUIRED")
        snapshot = claim_step(session, task_id)
        if snapshot is None:
            return
        case = session.get(OutreachCase, task.case_id)
        try:
            reserve_model_request(case, settings, "D07")
        except ModelUnavailable as error:
            finish_step(task, error_code=str(error))
            return
        methods = retrieve(
            session,
            {"responsibility", "results", "detail"},
            preview=task.detail.get("knowledge_preview", False),
            structured_only=True,
        )
        context = {
            "schema": Outline.model_json_schema(),
            "upstream": case.snapshot,
            "upstream_content": case.session_data.get("upstream_content"),
            "methods": methods,
            "dimensions": ["responsibility", "results"],
        }
    try:
        if not methods or not context["upstream_content"]:
            raise ModelUnavailable("INPUTS_NOT_READY")
        result = generate_json(settings, "Generate a Chinese interview outline as JSON.", context)
        outline = validate_outline(
            Outline.model_validate(result["content"]), methods, {"responsibility", "results"}
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
        artifact = save_artifact(
            session,
            case,
            "D07",
            {
                **outline.model_dump(),
                "retrieved_methods": methods,
                "knowledge_preview": task.detail.get("knowledge_preview", False),
            },
            {
                "source_mode": "live",
                "inherited_source_modes": ["mock"],
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
            "current_question": outline.questions[0].model_dump(),
            "knowledge_preview": task.detail.get("knowledge_preview", False),
        }
        case.revision += 1
        finish_step(task, result_ref={"id": artifact.id, "version": artifact.version})
