import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.core.auth import database_session, require_identity
from app.core.contracts import ScreeningPassedEvent
from app.modules.outreach.answers import (
    correct_answer,
    record_answer,
    record_candidate_stop,
    request_stop,
)
from app.modules.outreach.artifacts import (
    export_markdown,
    invalidate_downstream,
    locked_case,
    review_report,
)
from app.modules.outreach.curation import CuratedMethod, curate
from app.modules.outreach.http_models import (
    CallDetailView,
    CallListView,
    ModelTaskView,
    OutreachTaskAccepted,
    ReviewResult,
)
from app.modules.outreach.job_standard import JobInterviewStandard, bind_confirmed_standard
from app.modules.outreach.knowledge import MethodDocument, MethodEntry, retrieve
from app.modules.outreach.models import ModelStep, OutreachArtifact, OutreachCase, ReportAudit
from app.modules.outreach.service import consume_fixture
from app.modules.outreach.steps import register_step, retry_step
from app.modules.outreach.voice import confirm_mock_stop, mock_callback, start_mock

# Backend B adds call/report routes here without editing Backend A's module.
router = APIRouter(tags=["outreach"])


@router.websocket("/candidate/calls/{case_id}/stream")
async def candidate_audio_stream(socket: WebSocket, case_id: str):
    import asyncio
    from types import SimpleNamespace

    from app.integrations.voice.streaming import transcribe_stream
    from app.modules.outreach.budget import reserve_model_request
    from app.modules.outreach.preflight import require_preflight

    if socket.headers.get("origin") not in socket.app.state.settings.allowed_origins:
        await socket.close(code=1008)
        return
    await socket.accept()
    task_id = None
    try:
        async with asyncio.timeout(10):
            hello = await socket.receive_json()
        token = hello.get("token", "")
        if not isinstance(token, str) or len(token) > 128:
            raise ValueError("INVITATION_INVALID")
        request = SimpleNamespace(headers={"authorization": "Bearer " + token}, app=socket.app)
        with database_session(request) as session, session.begin():
            case = candidate_case(session, case_id, request)
            from app.modules.outreach.processing_permissions import require_processing_permission

            require_processing_permission(case, "transcription")
            revision = hello.get("expected_revision")
            if (
                case.revision != revision
                or case.stop_status != "none"
                or case.status in {"ended", "cancelled"}
            ):
                raise ValueError("INTERVIEW_INPUT_CHANGED")
            if case.session_data.get("preflight", {}).get("confirmed"):
                require_preflight(case)
                require_current_execution_outline(session, case)
            if case.session_data.get("decision_status") == "pending":
                raise ValueError("DECISION_PENDING")
            task, created = register_step(session, case.id, "transcription", case.revision)
            if not created:
                raise ValueError("TRANSCRIPTION_REQUIRES_RECONCILIATION")
            reserve_model_request(case, socket.app.state.settings, "stream_transcription")
            task.status = "running"
            task.detail = {**task.detail, "transport": "browser_pcm_stream"}
            task_id = task.id
        await socket.send_json({"type": "ready", "task_id": task_id})

        def validate_current():
            with database_session(request) as session:
                case = candidate_case(session, case_id, request)
                if (
                    case.revision != revision
                    or case.stop_status != "none"
                    or case.status in {"ended", "cancelled"}
                ):
                    raise ValueError("INTERVIEW_INPUT_CHANGED")

        async def frames():
            while True:
                message = await socket.receive()
                if message["type"] == "websocket.disconnect":
                    raise RuntimeError("STREAM_DISCONNECTED")
                await asyncio.to_thread(validate_current)
                if message.get("bytes") is not None:
                    yield message["bytes"]
                elif message.get("text") == "finish":
                    break
                else:
                    raise ValueError("STREAM_FRAME_INVALID")

        async def emit(event):
            await asyncio.to_thread(validate_current)
            await socket.send_json(event)

        result = await transcribe_stream(socket.app.state.settings, frames(), emit)
        with database_session(request) as session, session.begin():
            case = candidate_case(session, case_id, request)
            if (
                case.revision != revision
                or case.stop_status != "none"
                or case.status in {"ended", "cancelled"}
            ):
                raise ValueError("INTERVIEW_INPUT_CHANGED")
            task = session.get(ModelStep, task_id, with_for_update=True)
            from app.modules.outreach.interview import termination_reason

            stopped = termination_reason(result["text"], 0, 0) == "candidate_requested_stop"
            if stopped:
                if case.session_data.get("attempts"):
                    case.stop_status = "requested"
                    confirm_mock_stop(case)
                case.status = "ended"
                case.stop_status = "confirmed"
                case.session_data = {
                    **case.session_data,
                    "termination_reason": "candidate_requested_stop",
                    "decision_status": "stopped",
                    "candidate_stop_statement": result["text"],
                    "stop_transcription_task_id": task_id,
                }
                case.revision += 1
            task.status = "completed"
            result = {
                **result,
                "revision": revision,
                "transcription_task_id": task_id,
                "stopped": stopped,
            }
            task.detail = {**task.detail, "result": result}
        await socket.send_json({"type": "transcript_completed", **result})
        await socket.close()
    except Exception as error:
        if task_id:
            with database_session(socket) as session, session.begin():
                task = session.get(ModelStep, task_id, with_for_update=True)
                if task and task.status == "running":
                    task.status = "failed"
                    task.detail = {
                        **task.detail,
                        "error_code": "STREAM_RESULT_REQUIRES_RECONCILIATION",
                        "failure_kind": type(error).__name__,
                    }
        try:
            code = str(error)
            await socket.send_json(
                {
                    "type": "error",
                    "code": code if code in OUTLINE_CONFLICTS else "STREAM_NOT_COMPLETED",
                }
            )
            await socket.close(code=1008)
        except RuntimeError:
            pass


@router.get("/interview-tasks/{task_id}", response_model=ModelTaskView)
def model_task(task_id: str, request: Request):
    identity = require_identity(request)
    with database_session(request) as session:
        task = session.get(ModelStep, task_id)
        if task is None:
            raise HTTPException(404)
        try:
            locked_case(session, task.case_id, identity["organization_id"], identity["user_id"])
        except LookupError:
            raise HTTPException(404) from None
        return {
            "id": task.id,
            "kind": task.step,
            "status": task.status,
            "resource_type": "call",
            "resource_id": task.case_id,
            "input_revision": task.input_revision,
            "detail": task.detail,
            "poll_after_ms": 3000,
        }


@router.get("/knowledge/entries")
def list_methods(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    structured_only: bool = False,
):
    require_identity(request)
    if request.app.state.settings.environment != "development":
        raise HTTPException(403)
    with database_session(request) as session:
        criteria = []
        if structured_only:
            criteria.append(
                MethodEntry.content["extraction_status"]
                .as_string()
                .in_(["structured_pending_review", "curated"])
            )
        total = session.scalar(select(func.count()).select_from(MethodEntry).where(*criteria))
        entries = session.scalars(
            select(MethodEntry)
            .where(*criteria)
            .order_by(MethodEntry.document_id, MethodEntry.paragraph)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = []
        for entry in entries:
            doc = session.get(MethodDocument, entry.document_id)
            items.append(
                {
                    "entry_id": entry.id,
                    "review_status": entry.review_status,
                    "enabled": entry.enabled,
                    "content": entry.content,
                    "source": {
                        "filename": doc.filename,
                        "version": doc.version,
                        "paragraph": entry.paragraph,
                        "sha256": doc.sha256,
                    },
                }
            )
        return {"items": items, "total": total, "page": page, "page_size": page_size}


class CurationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: CuratedMethod
    approve: bool = False


class MethodEnabledInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


@router.post("/knowledge/{entry_id}/enabled")
def enable_method(entry_id: str, data: MethodEnabledInput, request: Request):
    require_identity(request)
    if request.app.state.settings.environment != "development":
        raise HTTPException(403)
    with database_session(request) as session, session.begin():
        entry = session.scalar(
            select(MethodEntry).where(MethodEntry.id == entry_id).with_for_update()
        )
        if entry is None:
            raise HTTPException(404)
        entry.enabled = data.enabled
        return {"id": entry.id, "enabled": entry.enabled, "review_status": entry.review_status}


@router.post("/knowledge/{entry_id}/curate")
def curate_method(entry_id: str, data: CurationInput, request: Request):
    identity = require_identity(request)
    if request.app.state.settings.environment != "development":
        raise HTTPException(403)
    with database_session(request) as session, session.begin():
        entry = session.scalar(
            select(MethodEntry).where(MethodEntry.id == entry_id).with_for_update()
        )
        if entry is None:
            raise HTTPException(404)
        try:
            curate(entry, data.method, identity["user_id"], data.approve)
        except ValueError:
            raise HTTPException(409) from None
        return {"id": entry.id, "review_status": entry.review_status, "content": entry.content}


class FixtureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch: str = Field(default="default", pattern=r"^[a-zA-Z0-9_-]{1,64}$")


@router.post("/dev/fixture")
def create_fixture(request: Request, data: FixtureInput):
    identity = require_identity(request)
    if request.app.state.settings.environment != "development":
        raise HTTPException(403)
    path = Path(__file__).resolve().parents[4] / "docs/contracts/day1_screening_passed.example.json"
    if not path.is_file():
        # Some runtime images intentionally omit repository documentation/fixtures.
        raise HTTPException(503, detail="FIXTURE_NOT_PACKAGED")
    payload = json.loads(path.read_text(encoding="utf8"))
    payload["organization_id"] = identity["organization_id"]
    if data.batch != "default":
        for key in ("event_id", "application_id", "candidate_id"):
            payload[key] = f"{payload[key]}-{data.batch}"
    event = ScreeningPassedEvent.model_validate(payload)
    with database_session(request) as session, session.begin():
        case = consume_fixture(session, event, identity["user_id"])
        if "upstream_content" not in case.session_data:
            content_path = Path(__file__).resolve().parents[3] / "config/fixture-upstream.v1.json"
            content = json.loads(content_path.read_text(encoding="utf8"))
            case.session_data = {**case.session_data, "upstream_content": content}
            case.revision += 1
        return case_view(case)


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    expected_revision: int = Field(ge=1)
    action: Literal["approve", "reject"]
    reason: str = Field(min_length=1, max_length=2000)


def report_for_user(session, report_id, identity, *, check_source_conflicts=False):
    report = session.get(OutreachArtifact, report_id)
    if report is None or report.type != "D10":
        raise HTTPException(404)
    try:
        case = locked_case(
            session, report.case_id, identity["organization_id"], identity["user_id"]
        )
    except LookupError:
        raise HTTPException(404) from None
    evaluation = session.scalar(
        select(OutreachArtifact).where(
            OutreachArtifact.case_id == report.case_id,
            OutreachArtifact.type == "D09",
            OutreachArtifact.valid.is_(True),
        )
    )
    if evaluation is None or evaluation.content.get("conclusion") != "recommended":
        raise HTTPException(409)
    if not any(
        ref.get("id") == evaluation.id and ref.get("version") == evaluation.version
        for ref in report.input_refs
    ):
        raise HTTPException(409)
    if check_source_conflicts and report_has_source_conflicts(session, case, evaluation):
        raise ReportSourceConflict
    return session.scalar(
        select(OutreachArtifact)
        .where(OutreachArtifact.id == report_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )


def report_has_source_conflicts(session, case, evaluation):
    from app.modules.outreach.career_confirmation import (
        confirmed_upstream,
        unresolved_career_conflicts,
    )

    conflicts = evaluation.content.get("conflicts")
    if not conflicts:
        return False
    for ref in evaluation.input_refs:
        ref_id = ref.get("id")
        minutes = session.get(OutreachArtifact, ref_id) if ref_id else None
        if (
            minutes is not None
            and minutes.case_id == case.id
            and minutes.type == "D08"
            and minutes.valid
            and minutes.version == ref.get("version")
            and minutes.content.get("conflicts") == conflicts
        ):
            _, confirmations = confirmed_upstream(case, minutes)
            return bool(unresolved_career_conflicts(case, minutes, confirmations))
    return True


class ReportSourceConflict(Exception):
    """The referenced evaluation still records unresolved source conflicts."""


def report_source_conflict(request: Request):
    code = "REPORT_FACT_CONFLICT_REQUIRES_CORRECTION"
    return conflict_response(request, code, allowed={code})


@router.post("/reports/{report_id}/review", response_model=ReviewResult)
def review(report_id: str, data: ReviewInput, request: Request):
    identity = require_identity(request)
    with database_session(request) as session, session.begin():
        try:
            report = report_for_user(
                session, report_id, identity, check_source_conflicts=data.action == "approve"
            )
        except ReportSourceConflict:
            return report_source_conflict(request)
        try:
            if data.action == "approve":
                from app.modules.outreach.client_sharing import require_client_sharing

                require_client_sharing(session.get(OutreachCase, report.case_id))
            review_report(
                report,
                data.expected_version,
                data.expected_revision,
                data.action,
                identity["user_id"],
                data.reason,
            )
        except ValueError:
            raise HTTPException(409) from None
        session.add(
            ReportAudit(
                id=uuid4().hex,
                report_id=report.id,
                version=report.version,
                action=data.action,
                request_id=request.state.request_id,
                actor_id=identity["user_id"],
                detail={"reason": data.reason, "at": datetime.now(UTC).isoformat()},
            )
        )
        return {
            "id": report.id,
            "version": report.version,
            "revision": report.revision,
            "status": report.review_status,
        }


@router.get("/reports/{report_id}/export")
def download_report(
    report_id: str,
    request: Request,
    version: int = Query(ge=1),
    format: Literal["markdown", "docx"] = "markdown",
):
    identity = require_identity(request)
    export_id = request.headers.get("x-export-request-id", "")
    if (
        not 8 <= len(export_id) <= 128
        or not export_id.isascii()
        or not all(c.isalnum() or c in "-_" for c in export_id)
    ):
        raise HTTPException(422)
    with database_session(request) as session, session.begin():
        try:
            report = report_for_user(session, report_id, identity, check_source_conflicts=True)
        except ReportSourceConflict:
            return report_source_conflict(request)
        if report.version != version:
            raise HTTPException(409)
        try:
            from app.modules.outreach.client_sharing import require_client_sharing

            require_client_sharing(session.get(OutreachCase, report.case_id))
            content = export_markdown(report)
        except ValueError:
            raise HTTPException(409) from None
        action = "word_download" if format == "docx" else "markdown_download"
        if format == "docx":
            from app.modules.outreach.report_document import report_docx

            content = report_docx(content)
        audit = session.scalar(
            select(ReportAudit).where(
                ReportAudit.report_id == report.id,
                ReportAudit.action == action,
                ReportAudit.request_id == export_id,
            )
        )
        if audit is None:
            session.add(
                ReportAudit(
                    id=uuid4().hex,
                    report_id=report.id,
                    version=report.version,
                    action=action,
                    request_id=export_id,
                    actor_id=identity["user_id"],
                    detail={
                        "status": "export_response_issued",
                        "at": datetime.now(UTC).isoformat(),
                    },
                )
            )
        extension = "docx" if format == "docx" else "md"
        return Response(
            content,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if format == "docx"
            else "text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="recommendation-v{version}.{extension}"'
                ),
                "Cache-Control": "no-store",
            },
        )


class OutlineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    knowledge_preview: bool = False


class AnswerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    answer: str = Field(min_length=1, max_length=10000)


class EvaluationStandardInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    standard: JobInterviewStandard
    threshold: float = Field(ge=1, le=10)
    report_template_version: int = Field(ge=1)


@router.post("/calls/{case_id}/evaluation-standard")
def confirm_evaluation_standard(case_id: str, data: EvaluationStandardInput, request: Request):
    identity = require_identity(request)
    with database_session(request) as session, session.begin():
        try:
            case = locked_case(session, case_id, identity["organization_id"], identity["user_id"])
            return bind_confirmed_standard(
                session,
                case,
                data.standard,
                threshold=data.threshold,
                report_template_version=data.report_template_version,
                expected_revision=data.expected_revision,
                actor_id=identity["user_id"],
            )
        except LookupError:
            raise HTTPException(404) from None
        except ValueError as error:
            raise HTTPException(409, detail=str(error)) from None


@router.post("/calls/{case_id}/answers/{answer_id}/corrections")
def correct_interview_answer(case_id: str, answer_id: str, data: AnswerInput, request: Request):
    identity = require_identity(request)
    with database_session(request) as session, session.begin():
        try:
            case = locked_case(session, case_id, identity["organization_id"], identity["user_id"])
            revised = correct_answer(
                case, answer_id, data.answer, data.expected_revision, identity["user_id"]
            )
            invalidate_downstream(session, case, "D07")
        except LookupError:
            raise HTTPException(404) from None
        except ValueError:
            raise HTTPException(409) from None
        return {
            "answer_id": revised["id"],
            "version": revised["version"],
            "revision": case.revision,
        }


class RevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)


@router.post(
    "/interview-tasks/{task_id}/retry", status_code=202, response_model=OutreachTaskAccepted
)
def retry_model_task(task_id: str, data: RevisionInput, request: Request):
    identity = require_identity(request)
    with database_session(request) as session, session.begin():
        task = session.get(ModelStep, task_id, with_for_update=True)
        if task is None:
            raise HTTPException(404)
        try:
            case = locked_case(
                session, task.case_id, identity["organization_id"], identity["user_id"]
            )
            if case.revision != data.expected_revision:
                raise ValueError("VERSION_CONFLICT")
            if task.step == "D09":
                blocked = evaluation_enqueue_conflict(session, case, request)
                if blocked is not None:
                    return blocked
            retry_step(task, case, identity["user_id"])
        except LookupError:
            raise HTTPException(404) from None
        except ValueError:
            raise HTTPException(409) from None
        return {
            "task_id": task.id,
            "resource_type": "call",
            "resource_id": case.id,
            "poll_after_ms": 3000,
        }


class EnqueueInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    step: Literal["D07", "followup", "D08", "D09", "D10"]
    knowledge_preview: bool = False


def evaluation_enqueue_conflict(session, case, request: Request):
    from app.modules.outreach.minutes import require_evaluation_ready

    minutes = session.scalar(
        select(OutreachArtifact).where(
            OutreachArtifact.case_id == case.id,
            OutreachArtifact.type == "D08",
            OutreachArtifact.valid.is_(True),
        )
    )
    if minutes is None:
        code = "EVALUATION_READY_EXTRACTION_REQUIRED"
        return conflict_response(request, code, allowed={code})
    try:
        require_evaluation_ready(case, minutes)
    except ValueError as error:
        return conflict_response(request, str(error), allowed={"MINUTES_REVIEW_REQUIRED"})
    return None


@router.post("/calls/{case_id}/steps", status_code=202, response_model=OutreachTaskAccepted)
def enqueue_model_step(case_id: str, data: EnqueueInput, request: Request):
    identity = require_identity(request)
    if data.knowledge_preview and request.app.state.settings.environment != "development":
        raise HTTPException(403)
    with database_session(request) as session, session.begin():
        try:
            case = locked_case(session, case_id, identity["organization_id"], identity["user_id"])
        except LookupError:
            raise HTTPException(404) from None
        if case.revision != data.expected_revision:
            raise HTTPException(409)
        if data.step in {"D07", "followup"} and case.stop_status != "none":
            raise HTTPException(409)
        if data.step == "D09":
            blocked = evaluation_enqueue_conflict(session, case, request)
            if blocked is not None:
                return blocked
        task, created = register_step(session, case.id, data.step, case.revision)
        if created:
            task.detail = {
                **task.detail,
                "knowledge_preview": data.knowledge_preview,
                "actor_id": identity["user_id"],
                "organization_id": identity["organization_id"],
            }
        elif task.detail.get("knowledge_preview", False) != data.knowledge_preview:
            raise HTTPException(409)
        return {
            "task_id": task.id,
            "resource_type": "call",
            "resource_id": case.id,
            "poll_after_ms": 3000,
            "status": task.status,
        }


class MockCallbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    callback_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=1)
    status: Literal["in_progress", "completed", "interrupted", "failed"]


@router.post("/calls/{case_id}/mock-callback")
def receive_mock_callback(case_id: str, data: MockCallbackInput, request: Request):
    identity = require_identity(request)
    if request.app.state.settings.environment != "development":
        raise HTTPException(403)
    with database_session(request) as session, session.begin():
        try:
            case = locked_case(session, case_id, identity["organization_id"], identity["user_id"])
            if not case.snapshot.get("fixture_only"):
                raise ValueError("FIXTURE_REQUIRED")
            mock_callback(case, data.callback_id, data.sequence, data.status)
        except LookupError:
            raise HTTPException(404) from None
        except ValueError:
            raise HTTPException(409) from None
        return case_view(case)


@router.post("/calls/{case_id}/mock-start")
def mock_start(case_id: str, data: RevisionInput, request: Request):
    return mock_command(case_id, data, request, "start")


@router.post("/calls/{case_id}/mock-confirm-stop")
def mock_stop(case_id: str, data: RevisionInput, request: Request):
    return mock_command(case_id, data, request, "stop")


def mock_command(case_id, data, request, action):
    identity = require_identity(request)
    if request.app.state.settings.environment != "development":
        raise HTTPException(403)
    with database_session(request) as session, session.begin():
        try:
            case = locked_case(session, case_id, identity["organization_id"], identity["user_id"])
            if case.revision != data.expected_revision:
                raise ValueError("VERSION_CONFLICT")
            if action == "start":
                start_mock(case, data.expected_revision)
            else:
                confirm_mock_stop(case)
        except LookupError:
            raise HTTPException(404) from None
        except ValueError:
            raise HTTPException(409) from None
        return case_view(case)


@router.post("/calls/{case_id}/evaluation", status_code=202)
def create_evaluation(case_id: str, data: RevisionInput, request: Request):
    return enqueue_model_step(
        case_id,
        EnqueueInput(expected_revision=data.expected_revision, step="D09", knowledge_preview=False),
        request,
    )


@router.post("/calls/{case_id}/recommendation", status_code=202)
def create_recommendation(case_id: str, data: RevisionInput, request: Request):
    return enqueue_model_step(
        case_id,
        EnqueueInput(expected_revision=data.expected_revision, step="D10", knowledge_preview=False),
        request,
    )


@router.post("/calls/{case_id}/minutes", status_code=202)
def create_minutes(case_id: str, data: RevisionInput, request: Request):
    return enqueue_model_step(
        case_id,
        EnqueueInput(expected_revision=data.expected_revision, step="D08", knowledge_preview=False),
        request,
    )


@router.post("/calls/{case_id}/followup", status_code=202)
def next_question(case_id: str, data: RevisionInput, request: Request):
    return enqueue_model_step(
        case_id,
        EnqueueInput(
            expected_revision=data.expected_revision, step="followup", knowledge_preview=False
        ),
        request,
    )


@router.post("/calls/{case_id}/answers")
def submit_answer(case_id: str, data: AnswerInput, request: Request):
    from app.modules.outreach.interview import termination_reason

    identity = require_identity(request)
    with database_session(request) as session, session.begin():
        try:
            case = locked_case(session, case_id, identity["organization_id"], identity["user_id"])
            if termination_reason(data.answer, 0, 0) == "candidate_requested_stop":
                record_candidate_stop(case, data.answer, data.expected_revision)
            else:
                record_answer(case, data.answer, data.expected_revision)
                invalidate_downstream(session, case, "D07")
        except LookupError:
            raise HTTPException(404) from None
        except ValueError:
            raise HTTPException(409) from None
        return case_view(case)


@router.post("/calls/{case_id}/cancel")
def cancel_interview(case_id: str, data: RevisionInput, request: Request):
    identity = require_identity(request)
    with database_session(request) as session, session.begin():
        try:
            case = locked_case(session, case_id, identity["organization_id"], identity["user_id"])
            request_stop(case, data.expected_revision)
        except LookupError:
            raise HTTPException(404) from None
        except ValueError:
            raise HTTPException(409) from None
        return case_view(case)


@router.post("/calls/{case_id}/outline", status_code=202)
def create_outline(case_id: str, data: OutlineInput, request: Request):
    return enqueue_model_step(
        case_id,
        EnqueueInput(
            expected_revision=data.expected_revision,
            step="D07",
            knowledge_preview=data.knowledge_preview,
        ),
        request,
    )


def case_view(case):
    return {
        "id": case.id,
        "application_id": case.application_id,
        "candidate_id": case.candidate_id,
        "job_id": case.job_id,
        "revision": case.revision,
        "status": case.status,
        "stop_status": case.stop_status,
        "fixture_only": True,
        "inherited_source_modes": ["mock"],
        "session": case.session_data,
        "upstream_refs": case.snapshot["artifact_refs"],
    }


@router.post("/dev/screening-passed")
def fixture_screening(event: ScreeningPassedEvent, request: Request):
    identity = require_identity(request)
    if request.app.state.settings.environment != "development":
        raise HTTPException(403)
    if event.organization_id != identity["organization_id"]:
        raise HTTPException(404)
    with database_session(request) as session, session.begin():
        try:
            return case_view(consume_fixture(session, event, identity["user_id"]))
        except ValueError:
            raise HTTPException(409) from None


@router.get("/calls", response_model=CallListView)
def calls(request: Request, application_id: str | None = Query(None, min_length=1, max_length=128)):
    identity = require_identity(request)
    with database_session(request) as session:
        query = select(OutreachCase).where(
            OutreachCase.organization_id == identity["organization_id"],
            OutreachCase.owner_id == identity["user_id"],
        )
        if application_id is not None:
            query = query.where(OutreachCase.application_id == application_id)
        items = list(session.scalars(query.order_by(OutreachCase.id)))
        return {
            "items": [case_view(case) for case in items],
            "total": len(items),
            "page": 1,
            "page_size": len(items),
        }


@router.get("/calls/{case_id}", response_model=CallDetailView)
def call_detail(case_id: str, request: Request):
    identity = require_identity(request)
    with database_session(request) as session:
        try:
            case = locked_case(session, case_id, identity["organization_id"], identity["user_id"])
        except LookupError:
            raise HTTPException(404) from None
        artifacts = list(
            session.scalars(
                select(OutreachArtifact).where(
                    OutreachArtifact.case_id == case_id,
                )
            )
        )
        from app.modules.outreach.career_confirmation import confirmed_upstream

        current_minutes = next((a for a in artifacts if a.type == "D08" and a.valid), None)
        career_upstream, active_confirmations = confirmed_upstream(case, current_minutes)
        return {
            **case_view(case),
            "session": {
                **case.session_data,
                "career_confirmed_upstream": career_upstream,
                "active_career_confirmation_ids": [r.get("id") for r in active_confirmations],
            },
            "failed_tasks": [
                {
                    "id": task.id,
                    "status": task.status,
                    "step": task.step,
                    "input_revision": task.input_revision,
                    "error_code": task.detail.get("error_code"),
                    "retry_count": task.detail.get("retry_count", 0),
                }
                for task in session.scalars(
                    select(ModelStep)
                    .where(ModelStep.case_id == case_id, ModelStep.status == "failed")
                    .order_by(ModelStep.input_revision.desc(), ModelStep.id)
                    .limit(20)
                )
            ],
            "active_tasks": [
                {"id": task.id, "status": task.status, "step": task.step}
                for task in session.scalars(
                    select(ModelStep)
                    .where(
                        ModelStep.case_id == case_id, ModelStep.status.in_(["queued", "running"])
                    )
                    .order_by(ModelStep.id)
                )
            ],
            "artifacts": [
                {
                    "id": a.id,
                    "type": a.type,
                    "version": a.version,
                    "valid": a.valid,
                    "revision": a.revision,
                    "review_status": a.review_status,
                    "content": a.content,
                    "provenance": a.provenance,
                    "input_refs": a.input_refs,
                }
                for a in artifacts
            ],
        }


@router.get("/knowledge/search")
def search_methods(request: Request, tags: str = Query(max_length=200), preview: bool = False):
    require_identity(request)
    if preview and request.app.state.settings.environment != "development":
        raise HTTPException(403)
    with database_session(request) as session:
        return {
            "items": retrieve(session, set(tags.split(",")), preview=preview, structured_only=True),
            "preview": preview,
        }


class PreflightInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    action: Literal["interest", "mock_email", "confirm"]
    statement: str = Field(min_length=1, max_length=2000)
    interested: bool | None = None
    email: str | None = Field(default=None, max_length=254)
    request_id: str | None = Field(default=None, max_length=128)
    material_sha256: str | None = Field(default=None, max_length=64)


class InvitationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    action: Literal["issue", "revoke"]
    lifetime_seconds: int = Field(default=3600, ge=60, le=86400)


def candidate_case(session, case_id: str, request: Request):
    from app.modules.outreach.invitations import validate_invitation

    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer ") or len(authorization) > 256:
        raise HTTPException(401)
    case = session.scalar(select(OutreachCase).where(OutreachCase.id == case_id).with_for_update())
    if case is None:
        raise HTTPException(401)
    try:
        validate_invitation(case, authorization[7:])
    except ValueError:
        raise HTTPException(401) from None
    return case


def current_execution_outline(session, case):
    outline_id = case.session_data.get("outline_id")
    return session.get(OutreachArtifact, outline_id) if outline_id else None


def require_current_execution_outline(session, case):
    from app.modules.outreach.outline_inputs import require_execution_outline

    require_execution_outline(case, current_execution_outline(session, case))


def conflict_response(request: Request, code: str, *, allowed: set[str]):
    return JSONResponse(
        status_code=409,
        content={
            "code": code if code in allowed else "HTTP_409",
            "message": "Request conflicts with current state",
            "request_id": request.state.request_id,
            "details": None,
        },
    )


OUTLINE_CONFLICTS = {
    "OUTLINE_BLOCKED",
    "OUTLINE_READINESS_REVIEW_REQUIRED",
    "OUTLINE_REGENERATION_REQUIRED",
}
CAREER_CONFLICTS = {
    "VERSION_CONFLICT",
    "CURRENT_MINUTES_REQUIRED",
    "CAREER_CONFIRMATION_REQUIRED",
    "CAREER_SOURCE_QUOTE_INVALID",
    "CAREER_SOURCE_STRUCTURE_INVALID",
    "CAREER_FIELD_INVALID",
    "CAREER_CONFLICT_REFERENCE_INVALID",
    "CAREER_CONFLICT_EVIDENCE_MISMATCH",
    "CAREER_CONFIRMATION_NOT_FOUND",
    "CAREER_CONFIRMATION_ALREADY_REVOKED",
}


class OutlineLimitationsReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    expected_version: int = Field(ge=1)
    rationale: str = Field(min_length=1, max_length=2000)


@router.post("/calls/{case_id}/outline-limitations-review")
def review_outline_limitations(case_id: str, data: OutlineLimitationsReviewInput, request: Request):
    from app.modules.outreach.outline_inputs import approve_outline_limitations

    identity = require_identity(request)
    with database_session(request) as session, session.begin():
        try:
            case = locked_case(session, case_id, identity["organization_id"], identity["user_id"])
            receipt = approve_outline_limitations(
                case,
                current_execution_outline(session, case),
                **data.model_dump(),
                reviewer_id=identity["user_id"],
            )
        except LookupError:
            raise HTTPException(404) from None
        except ValueError as error:
            session.rollback()
            return conflict_response(
                request,
                str(error),
                allowed=OUTLINE_CONFLICTS
                | {
                    "VERSION_CONFLICT",
                    "INTERVIEW_STOPPED",
                    "OUTLINE_LIMITATIONS_REVIEW_NOT_APPLICABLE",
                    "OUTLINE_LIMITATIONS_REVIEW_INVALID",
                },
            )
        return {"revision": case.revision, "review": receipt}


def candidate_view(case):
    import hashlib
    import time

    from app.modules.outreach.preflight import briefing_snapshot

    state = case.session_data.get("preflight", {})
    material = briefing_snapshot(case)
    digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    material.pop("upstream_refs", None)
    from app.modules.outreach.conversation import spoken_prompt
    from app.modules.outreach.conversation_options import limits, voice_catalog, voice_id

    return {
        "spoken_prompt": spoken_prompt(case),
        "voice_id": voice_id(case),
        "voices": voice_catalog(),
        "interview_limits": limits(case),
        "elapsed_seconds": int(time.time() - case.session_data["started_at"])
        if case.session_data.get("started_at")
        else 0,
        "practice_available": bool(
            case.snapshot.get("fixture_only") and case.session_data.get("outline_id")
        ),
        "revision": case.revision,
        "status": case.status,
        "stop_status": case.stop_status,
        "termination_reason": case.session_data.get("termination_reason"),
        "material": material,
        "material_sha256": digest,
        "preflight": {
            key: state.get(key) for key in ("interested", "confirmed", "briefing_presented")
        },
        "processing_permissions": {
            purpose: receipt.get("status")
            for purpose, receipt in case.session_data.get("processing_permissions", {}).items()
        },
        "client_sharing": {
            "client_label": case.session_data["client_context"]["candidate_client_label"],
            "status": (case.session_data.get("client_sharing") or {}).get("status", "UNKNOWN"),
        }
        if case.session_data.get("client_context")
        else None,
        "question": (case.session_data.get("current_question") or {}).get("question")
        if state.get("confirmed")
        else None,
        "decision_status": case.session_data.get("decision_status"),
        "turn_history": [
            {"question": answer.get("question", {}).get("question", ""), "answer": answer["text"]}
            for answer in case.session_data.get("answers", [])
            if answer.get("actor_type") == "candidate_invitation"
        ],
    }


@router.get("/candidate/calls/{case_id}")
def candidate_session(case_id: str, request: Request):
    from app.modules.outreach.conversation_options import enforce_duration

    with database_session(request) as session, session.begin():
        case = candidate_case(session, case_id, request)
        enforce_duration(case)
        result = candidate_view(case)
        if result.get("decision_status") == "pending":
            task = session.scalar(
                select(ModelStep).where(
                    ModelStep.case_id == case.id,
                    ModelStep.input_revision == case.revision,
                    ModelStep.step.in_(["followup", "conversation"]),
                )
            )
            if (
                task
                and task.status == "failed"
                and case.stop_status == "none"
                and case.status not in {"ended", "cancelled"}
            ):
                case.session_data = {
                    **case.session_data,
                    "decision_status": "completed",
                    "conversation_reply": (
                        "刚才后台处理回复时出了点问题，您的回答已保留。您可以继续，我在听。"
                    ),
                    "conversation_reply_model": None,
                    "conversation_reply_source": "program_clarification",
                    "conversation_recovered_task_id": task.id,
                }
                case.revision += 1
                result = candidate_view(case)
            result["decision_task"] = (
                {
                    "status": task.status,
                    "error_code": task.detail.get("error_code"),
                    "phase": task.detail.get("phase"),
                }
                if task
                else None
            )
        transcription = session.scalar(
            select(ModelStep).where(
                ModelStep.case_id == case.id,
                ModelStep.step == "transcription",
                ModelStep.input_revision == case.revision,
            )
        )
        if (
            transcription
            and case.stop_status == "none"
            and case.status not in {"ended", "cancelled"}
        ):
            if transcription.status == "failed":
                case.session_data = {
                    **case.session_data,
                    "transcription_recoveries": [
                        *case.session_data.get("transcription_recoveries", [])[-19:],
                        {"task_id": transcription.id, "input_revision": case.revision},
                    ],
                }
                case.revision += 1
                result = candidate_view(case)
            else:
                result["transcription"] = {
                    "status": transcription.status,
                    "task_id": transcription.id,
                    "text": transcription.detail.get("result", {}).get("text")
                    if transcription.status == "completed"
                    else None,
                    "error_code": transcription.detail.get("error_code"),
                }
        result["formal_outline_error"] = None
        if case.status not in {"ended", "cancelled"} and case.stop_status == "none":
            try:
                require_current_execution_outline(session, case)
            except ValueError as error:
                result["formal_outline_error"] = str(error)
                result["question"] = None
                if case.session_data.get("preflight", {}).get("confirmed"):
                    result["spoken_prompt"] = None
        return Response(
            content=json.dumps(result),
            media_type="application/json",
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )


class CandidateAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    action: Literal["interest", "confirm", "answer", "stop", "voice", "begin", "briefing_presented"]
    statement: str = Field(min_length=1, max_length=10000)
    interested: bool | None = None
    material_sha256: str | None = Field(default=None, max_length=64)
    transcription_task_id: str | None = Field(default=None, max_length=64)


class CandidateAudioInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    pcm_base64: str = Field(min_length=4, max_length=426668)


class BriefingEmailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    request_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,64}$")
    consent: Literal[True]


@router.post("/candidate/calls/{case_id}/briefing-email")
def candidate_briefing_email(case_id: str, data: BriefingEmailInput, request: Request):
    from app.core.auth import check_origin
    from app.modules.outreach.briefing_mail import mail_configured, validate_email
    from app.modules.outreach.preflight import briefing_snapshot

    check_origin(request)
    try:
        recipient = validate_email(data.email.strip())
    except ValueError:
        raise HTTPException(422, detail="EMAIL_INVALID") from None
    with database_session(request) as session, session.begin():
        case = candidate_case(session, case_id, request)
        if not mail_configured(request.app.state.settings):
            raise HTTPException(503, detail="MAIL_NOT_CONFIGURED")
        if not case.session_data.get("preflight", {}).get("interested"):
            raise HTTPException(409, detail="JOB_INTEREST_REQUIRED")
        if case.stop_status != "none" or case.status in {"ended", "cancelled"}:
            raise HTTPException(409, detail="INTERVIEW_STOPPED")
        import hashlib

        step = "briefing_email_" + hashlib.sha256(data.request_id.encode()).hexdigest()[:32]
        task, created = register_step(session, case.id, step, 1)
        material = briefing_snapshot(case)
        if created:
            existing_mail = list(
                session.scalars(
                    select(ModelStep).where(
                        ModelStep.case_id == case.id,
                        ModelStep.step.like("briefing_email_%"),
                        ModelStep.id != task.id,
                    )
                )
            )
            if any(t.status in {"queued", "running", "failed"} for t in existing_mail):
                raise HTTPException(409, detail="MAIL_REQUIRES_RECONCILIATION")
            count = session.scalar(
                select(func.count())
                .select_from(ModelStep)
                .where(ModelStep.case_id == case.id, ModelStep.step.like("briefing_email_%"))
            )
            if count > 3:
                raise HTTPException(409, detail="MAIL_SESSION_LIMIT")
            task.detail = {
                **task.detail,
                "recipient": recipient,
                "material": material,
                "consent": True,
            }
        elif task.detail.get("recipient") != recipient or task.detail.get("material") != material:
            raise HTTPException(409, detail="EMAIL_REQUEST_REUSED")
        return {
            "task_id": task.id,
            "status": task.status,
            "error_code": task.detail.get("error_code"),
        }


class CandidateSpeechInput(RevisionInput):
    preview: bool = False
    farewell: bool = False


class CandidateVoiceInput(RevisionInput):
    voice_id: str = Field(min_length=1, max_length=64)


class PracticeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,64}$")


@router.post("/candidate/calls/{case_id}/practice")
def candidate_practice(case_id: str, data: PracticeInput, request: Request):
    from app.core.auth import check_origin
    from app.modules.outreach.practice import create_practice

    check_origin(request)
    with database_session(request) as session, session.begin():
        source = candidate_case(session, case_id, request)
        try:
            case, token = create_practice(
                session,
                source,
                data.request_id,
                request.headers["authorization"][7:],
                request.app.state.settings,
            )
        except ValueError as error:
            raise HTTPException(409, detail=str(error)) from None
        return Response(
            content=json.dumps(
                {"case_id": case.id, "token": token, "session": candidate_view(case)}
            ),
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )


@router.post("/candidate/calls/{case_id}/voice")
def candidate_voice(case_id: str, data: CandidateVoiceInput, request: Request):
    from app.core.auth import check_origin
    from app.modules.outreach.conversation_options import voice_catalog

    check_origin(request)
    with database_session(request) as session, session.begin():
        case = candidate_case(session, case_id, request)
        if case.revision != data.expected_revision:
            raise HTTPException(409, detail="VERSION_CONFLICT")
        if case.status in {"ended", "cancelled"} or case.stop_status != "none":
            raise HTTPException(409, detail="INTERVIEW_STOPPED")
        if data.voice_id not in {item["id"] for item in voice_catalog()}:
            raise HTTPException(422, detail="VOICE_NOT_SUPPORTED")
        if case.session_data.get("decision_status") == "pending":
            raise HTTPException(409, detail="DECISION_PENDING")
        case.session_data = {**case.session_data, "voice_id": data.voice_id}
        case.revision += 1
        return Response(
            content=json.dumps(candidate_view(case)),
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )


@router.post("/candidate/calls/{case_id}/speech")
def candidate_speech(case_id: str, data: CandidateSpeechInput, request: Request):
    import base64

    from app.core.auth import check_origin
    from app.integrations.bailian import ModelUnavailable
    from app.integrations.voice.tts import synthesize_question
    from app.modules.outreach.budget import reserve_model_request
    from app.modules.outreach.conversation_options import voice_id
    from app.modules.outreach.preflight import require_preflight

    check_origin(request)
    with database_session(request) as session, session.begin():
        case = candidate_case(session, case_id, request)
        try:
            if case.revision != data.expected_revision and not data.farewell:
                raise ValueError("VERSION_CONFLICT")
            if (
                case.status in {"ended", "cancelled"} or case.stop_status != "none"
            ) and not data.farewell:
                raise ValueError("INTERVIEW_STOPPED")
            from app.modules.outreach.conversation import spoken_prompt

            if data.farewell and case.status not in {"ended", "cancelled"}:
                raise ValueError("FAREWELL_REQUIRES_ENDED_SESSION")
            if not data.farewell and case.session_data.get("preflight", {}).get("confirmed"):
                require_preflight(case)
                try:
                    require_current_execution_outline(session, case)
                except ValueError as error:
                    return conflict_response(request, str(error), allowed=OUTLINE_CONFLICTS)
            question = (
                "您好，我是您的AI面试官。我们可以像平时聊天一样交流，您也可以随时打断我。"
                if data.preview
                else spoken_prompt(case)
            )
            if not question or (
                not data.farewell and case.session_data.get("decision_status") == "pending"
            ):
                raise ValueError("QUESTION_NOT_READY")
            task, created = register_step(
                session,
                case.id,
                "farewell" if data.farewell else "voice_preview" if data.preview else "speech",
                case.revision,
            )
            if not created:
                if task.status != "completed":
                    raise ValueError("SPEECH_REQUIRES_RECONCILIATION")
                return Response(
                    content=json.dumps(task.detail["result"]),
                    media_type="application/json",
                    headers={"Cache-Control": "no-store"},
                )
            reserve_model_request(case, request.app.state.settings, "speech")
            task.status = "running"
            task_id = task.id
            voice = voice_id(case)
        except (ValueError, ModelUnavailable) as error:
            raise HTTPException(409, detail=str(error)) from None
    try:
        audio = synthesize_question(request.app.state.settings, question, voice=voice)
    except (RuntimeError, OSError, TimeoutError):
        with database_session(request) as session, session.begin():
            task = session.get(ModelStep, task_id, with_for_update=True)
            task.status = "failed"
            task.detail = {**task.detail, "error_code": "SPEECH_RESULT_UNKNOWN"}
        raise HTTPException(503, detail="SPEECH_UNAVAILABLE") from None
    result = {
        "timings": audio.get("timings"),
        "pcm_base64": base64.b64encode(audio["pcm"]).decode(),
        "sample_rate": audio["sample_rate"],
        "model": audio["model"],
        "source_mode": "live",
        "voice": voice,
    }
    with database_session(request) as session, session.begin():
        case = candidate_case(session, case_id, request)
        if not data.farewell and (
            case.revision != data.expected_revision
            or case.status in {"ended", "cancelled"}
            or case.stop_status != "none"
        ):
            raise HTTPException(409, detail="SPEECH_INPUT_CHANGED")
        if data.farewell and case.status not in {"ended", "cancelled"}:
            raise HTTPException(409, detail="FAREWELL_REQUIRES_ENDED_SESSION")
        task = session.get(ModelStep, task_id, with_for_update=True)
        task.status = "completed"
        task.detail = {**task.detail, "result": result}
    return Response(
        content=json.dumps(result),
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/candidate/calls/{case_id}/speech-stream")
def candidate_speech_stream(case_id: str, data: CandidateSpeechInput, request: Request):
    import base64

    from fastapi.responses import StreamingResponse

    from app.core.auth import check_origin
    from app.integrations.voice.tts import stream_question
    from app.modules.outreach.budget import reserve_model_request
    from app.modules.outreach.conversation import spoken_prompt
    from app.modules.outreach.conversation_options import voice_id

    check_origin(request)
    with database_session(request) as session, session.begin():
        case = candidate_case(session, case_id, request)
        if case.revision != data.expected_revision:
            raise HTTPException(409, detail="VERSION_CONFLICT")
        if case.status in {"ended", "cancelled"} or case.stop_status != "none":
            raise HTTPException(409, detail="INTERVIEW_STOPPED")
        if case.session_data.get("preflight", {}).get("confirmed"):
            try:
                require_current_execution_outline(session, case)
            except ValueError as error:
                return conflict_response(request, str(error), allowed=OUTLINE_CONFLICTS)
        if case.session_data.get("decision_status") == "pending":
            raise HTTPException(409, detail="DECISION_PENDING")
        text, voice = spoken_prompt(case), voice_id(case)
        if not text:
            raise HTTPException(409, detail="QUESTION_NOT_READY")
        task, created = register_step(session, case.id, "speech_stream", case.revision)
        if not created:
            raise HTTPException(409, detail="SPEECH_REQUIRES_RECONCILIATION")
        try:
            reserve_model_request(case, request.app.state.settings, "speech")
        except RuntimeError:
            raise HTTPException(409, detail="SPEECH_BUDGET_EXCEEDED") from None
        task.status = "running"
        task_id = task.id

    def events():
        completed = False
        try:
            stream = stream_question(request.app.state.settings, text, voice)
            for chunk in stream:
                yield (
                    json.dumps(
                        {
                            "type": "audio",
                            "pcm": base64.b64encode(chunk).decode(),
                            "sample_rate": 24000,
                        }
                    )
                    + "\n"
                )
            completed = True
            yield json.dumps({"type": "completed"}) + "\n"
        except (RuntimeError, OSError, TimeoutError, ValueError):
            yield json.dumps({"type": "error", "code": "SPEECH_UNAVAILABLE"}) + "\n"
        finally:
            with database_session(request) as session, session.begin():
                task = session.get(ModelStep, task_id, with_for_update=True)
                task.status = "completed" if completed else "failed"
                task.detail = {
                    **task.detail,
                    "error_code": None if completed else "SPEECH_INTERRUPTED",
                }

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post("/candidate/calls/{case_id}/transcription")
def candidate_transcription(case_id: str, data: CandidateAudioInput, request: Request):
    import base64
    import binascii
    import hashlib

    from app.core.auth import check_origin
    from app.integrations.bailian import ModelUnavailable
    from app.integrations.voice.realtime import audio_roundtrip
    from app.modules.outreach.budget import reserve_model_request
    from app.modules.outreach.preflight import require_preflight

    check_origin(request)
    try:
        pcm = base64.b64decode(data.pcm_base64, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422, detail="INVALID_PCM_BASE64") from None
    if not pcm or len(pcm) > 320000 or len(pcm) % 2:
        raise HTTPException(422, detail="PCM_16KHZ_MONO_S16LE_MAX_10_SECONDS_REQUIRED")
    with database_session(request) as session, session.begin():
        case = candidate_case(session, case_id, request)
        try:
            if case.revision != data.expected_revision:
                raise ValueError("VERSION_CONFLICT")
            if case.status in {"ended", "cancelled"} or case.stop_status != "none":
                raise ValueError("INTERVIEW_STOPPED")
            require_preflight(case)
            if case.session_data.get("decision_status") == "pending":
                raise ValueError("DECISION_PENDING")
            require_current_execution_outline(session, case)
            from app.modules.outreach.processing_permissions import require_processing_permission

            require_processing_permission(case, "transcription")
            digest = hashlib.sha256(pcm).hexdigest()
            receipt, created = register_step(session, case.id, "transcription", case.revision)
            if not created:
                if receipt.detail.get("pcm_sha256") != digest:
                    raise ValueError("TRANSCRIPTION_INPUT_CONFLICT")
                if receipt.status == "completed":
                    return Response(
                        content=json.dumps(receipt.detail["result"]),
                        media_type="application/json",
                        headers={"Cache-Control": "no-store"},
                    )
                raise ValueError("TRANSCRIPTION_REQUIRES_RECONCILIATION")
            reserve_model_request(case, request.app.state.settings, "transcription")
            receipt.status = "running"
            receipt.detail = {**receipt.detail, "pcm_sha256": digest}
            receipt_id = receipt.id
            revision = case.revision
        except (ValueError, ModelUnavailable) as error:
            if str(error) in OUTLINE_CONFLICTS:
                return conflict_response(request, str(error), allowed=OUTLINE_CONFLICTS)
            raise HTTPException(409, detail=str(error)) from None
    try:
        result = audio_roundtrip(request.app.state.settings, pcm, transcription_only=True)
    except (RuntimeError, OSError, TimeoutError):
        with database_session(request) as session, session.begin():
            receipt = session.get(ModelStep, receipt_id, with_for_update=True)
            receipt.status = "failed"
            receipt.detail = {**receipt.detail, "error_code": "TRANSCRIPTION_RESULT_UNKNOWN"}
        raise HTTPException(503, detail="TRANSCRIPTION_UNAVAILABLE") from None
    result = {**result, "transcription_task_id": receipt_id}
    with database_session(request) as session, session.begin():
        case = candidate_case(session, case_id, request)
        if (
            case.revision != revision
            or case.status in {"ended", "cancelled"}
            or case.stop_status != "none"
        ):
            raise HTTPException(409, detail="TRANSCRIPTION_INPUT_CHANGED")
        receipt = session.get(ModelStep, receipt_id, with_for_update=True)
        receipt.status = "completed"
        receipt.detail = {**receipt.detail, "result": {**result, "revision": revision}}
    return Response(
        content=json.dumps({**result, "revision": revision}),
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


class ProcessingPermissionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    purpose: Literal["formal_interview", "transcription", "extraction", "evaluation"]
    authorized: bool


@router.get("/evaluations/{artifact_id}/export")
@router.get("/minutes/{artifact_id}/export")
@router.get("/outlines/{artifact_id}/export")
def export_internal_evaluation(artifact_id: str, request: Request, version: int):
    from app.modules.outreach.evaluation_document import (
        evaluation_markdown,
        minutes_markdown,
        outline_markdown,
    )
    from app.modules.outreach.report_document import report_docx

    identity = require_identity(request)
    with database_session(request) as session:
        artifact = session.get(OutreachArtifact, artifact_id)
        expected_type = "D08" if "/minutes/" in request.url.path else "D09"
        if "/outlines/" in request.url.path:
            expected_type = "D07"
        if artifact is None or artifact.type != expected_type:
            raise HTTPException(404)
        try:
            locked_case(session, artifact.case_id, identity["organization_id"], identity["user_id"])
        except LookupError:
            raise HTTPException(404) from None
        export_kind = {"D07": "outline", "D08": "minutes", "D09": "evaluation"}[expected_type]
        if not artifact.valid or artifact.version != version:
            return JSONResponse(
                status_code=409,
                content={
                    "code": f"{export_kind.upper()}_VERSION_INVALID",
                    "message": "Artifact version is no longer current",
                    "request_id": request.state.request_id,
                    "details": None,
                },
            )
        renderers = {"D07": outline_markdown, "D08": minutes_markdown, "D09": evaluation_markdown}
        return Response(
            content=report_docx(renderers[expected_type](artifact)),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": (
                    f'attachment; filename="internal-{export_kind}-v{version}.docx"'
                ),
            },
        )


class CareerConfirmationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    minutes_id: str = Field(min_length=1, max_length=128)
    minutes_version: int = Field(ge=1)
    field_path: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=500)
    answer_id: str = Field(min_length=1, max_length=128)
    quote: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=2000)
    conflict_index: int | None = Field(default=None, ge=0)


@router.post("/calls/{case_id}/career-confirmations")
def confirm_career_field(case_id: str, data: CareerConfirmationInput, request: Request):
    from app.modules.outreach.career_confirmation import confirm_field

    identity = require_identity(request)
    with database_session(request) as session, session.begin():
        try:
            case = locked_case(session, case_id, identity["organization_id"], identity["user_id"])
            receipt = confirm_field(
                session, case, **data.model_dump(), actor_id=identity["user_id"]
            )
        except LookupError:
            raise HTTPException(404) from None
        except ValueError as error:
            session.rollback()
            return conflict_response(request, str(error), allowed=CAREER_CONFLICTS)
        return {"revision": case.revision, "confirmation": receipt}


class CareerRevocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)


@router.post("/calls/{case_id}/career-confirmations/{confirmation_id}/revoke")
def revoke_career_field(
    case_id: str, confirmation_id: str, data: CareerRevocationInput, request: Request
):
    from app.modules.outreach.career_confirmation import revoke_confirmation

    identity = require_identity(request)
    with database_session(request) as session, session.begin():
        try:
            case = locked_case(session, case_id, identity["organization_id"], identity["user_id"])
            revoke_confirmation(
                session,
                case,
                confirmation_id,
                data.expected_revision,
                data.reason,
                identity["user_id"],
            )
        except LookupError:
            raise HTTPException(404) from None
        except ValueError as error:
            session.rollback()
            return conflict_response(request, str(error), allowed=CAREER_CONFLICTS)
        return {"revision": case.revision}


class ClientContextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    client_company_id: str = Field(min_length=1, max_length=128)
    candidate_client_label: str = Field(min_length=1, max_length=200)


@router.post("/calls/{case_id}/client-context")
def configure_client_context(case_id: str, data: ClientContextInput, request: Request):
    from app.modules.outreach.client_sharing import set_client_context

    identity = require_identity(request)
    with database_session(request) as session, session.begin():
        try:
            case = locked_case(session, case_id, identity["organization_id"], identity["user_id"])
            set_client_context(
                session,
                case,
                data.client_company_id,
                data.candidate_client_label,
                data.expected_revision,
            )
        except LookupError:
            raise HTTPException(404) from None
        except ValueError as error:
            raise HTTPException(409, detail=str(error)) from None
        return {"revision": case.revision, "client_context": case.session_data["client_context"]}


class ClientSharingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    authorized: bool


@router.post("/candidate/calls/{case_id}/client-sharing")
def candidate_client_sharing(case_id: str, data: ClientSharingInput, request: Request):
    from app.core.auth import check_origin
    from app.modules.outreach.client_sharing import record_client_sharing

    check_origin(request)
    with database_session(request) as session, session.begin():
        case = candidate_case(session, case_id, request)
        try:
            record_client_sharing(session, case, data.authorized, data.expected_revision)
        except ValueError as error:
            raise HTTPException(409, detail=str(error)) from None
        return Response(
            content=json.dumps(candidate_view(case)),
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )


@router.post("/candidate/calls/{case_id}/processing-permissions")
def candidate_processing_permission(
    case_id: str, data: ProcessingPermissionInput, request: Request
):
    from app.core.auth import check_origin
    from app.modules.outreach.processing_permissions import record_processing_permission

    check_origin(request)
    with database_session(request) as session, session.begin():
        case = candidate_case(session, case_id, request)
        try:
            record_processing_permission(
                session, case, data.purpose, data.authorized, data.expected_revision
            )
        except ValueError as error:
            raise HTTPException(409, detail=str(error)) from None
        return Response(
            content=json.dumps(candidate_view(case)),
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )


@router.post("/candidate/calls/{case_id}")
def candidate_action(case_id: str, data: CandidateAction, request: Request):
    from app.core.auth import check_origin
    from app.modules.outreach.interview import termination_reason
    from app.modules.outreach.preflight import confirm_preflight, record_interest

    check_origin(request)
    with database_session(request) as session, session.begin():
        case = candidate_case(session, case_id, request)
        try:
            if case.revision != data.expected_revision:
                raise ValueError("VERSION_CONFLICT")
            if case.status in {"ended", "cancelled"} or case.stop_status != "none":
                raise ValueError("INTERVIEW_STOPPED")
            voice_transcription = None
            if (
                data.action == "answer"
                and termination_reason(data.statement, 0, 0) == "candidate_requested_stop"
            ):
                data.action = "stop"
            if data.action in {"begin", "answer", "voice"}:
                from app.modules.outreach.processing_permissions import (
                    require_processing_permission,
                )

                if termination_reason(data.statement, 0, 0) != "candidate_requested_stop":
                    for purpose in (
                        "formal_interview",
                        "transcription",
                        "extraction",
                        "evaluation",
                    ):
                        require_processing_permission(case, purpose)
            if data.action == "voice":
                from app.modules.outreach.conversation import consent

                voice_transcription = session.get(ModelStep, data.transcription_task_id or "")
                if (
                    voice_transcription is None
                    or voice_transcription.case_id != case.id
                    or voice_transcription.step != "transcription"
                    or voice_transcription.status != "completed"
                    or voice_transcription.input_revision != case.revision
                    or voice_transcription.detail.get("result", {}).get("text") != data.statement
                ):
                    raise ValueError("TRANSCRIPTION_REFERENCE_INVALID")
                state = case.session_data.get("preflight", {})
                from app.modules.outreach.conversation import spoken_prompt

                previous_prompt = spoken_prompt(case)
                case.session_data = {
                    **case.session_data,
                    "voice_clarification": None,
                    "conversation_reply": None,
                }
                if termination_reason(data.statement, 0, 0) == "candidate_requested_stop":
                    data.action = "stop"
                elif not state.get("confirmed"):
                    choice = consent(data.statement)
                    if choice is None:
                        case.session_data = {
                            **case.session_data,
                            "voice_clarification": True,
                            "voice_clarification_transcription_id": voice_transcription.id,
                            "conversation_utterance": data.statement,
                            "conversation_prompt": previous_prompt,
                            "decision_status": "pending",
                        }
                        case.revision += 1
                        register_step(session, case.id, "conversation", case.revision)
                        return Response(
                            content=json.dumps(candidate_view(case)),
                            media_type="application/json",
                            headers={"Cache-Control": "no-store"},
                        )
                    if not choice:
                        record_interest(case, False, data.statement)
                        data.action = "stop"
                    elif not state.get("interested") or not state.get("briefing_presented"):
                        data.action = "interest"
                        data.interested = True
                    else:
                        data.action = "confirm"
                        data.material_sha256 = candidate_view(case)["material_sha256"]
                else:
                    data.action = "answer"
            if data.action == "begin":
                import time

                if not case.session_data.get("started_at"):
                    case.session_data = {**case.session_data, "started_at": time.time()}
                    case.revision += 1
            elif data.action == "briefing_presented":
                state = case.session_data.get("preflight", {})
                if state.get("interested") is not True:
                    raise ValueError("JOB_INTEREST_REQUIRED")
                case.session_data = {
                    **case.session_data,
                    "preflight": {**state, "briefing_presented": True},
                }
                case.revision += 1
            elif data.action == "stop":
                # The request revision was checked above. Voice decline can record interest first.
                record_candidate_stop(case, data.statement, case.revision)
            elif data.action == "interest":
                if data.interested is None:
                    raise ValueError("INTEREST_REQUIRED")
                record_interest(case, data.interested, data.statement)
            elif data.action == "confirm":
                require_current_execution_outline(session, case)
                confirm_preflight(case, data.statement, data.material_sha256 or "")
            else:
                transcription = None
                if data.transcription_task_id:
                    transcription = session.get(ModelStep, data.transcription_task_id)
                    if (
                        transcription is None
                        or transcription.case_id != case.id
                        or transcription.step != "transcription"
                        or transcription.status != "completed"
                        or transcription.input_revision != case.revision
                    ):
                        raise ValueError("TRANSCRIPTION_REFERENCE_INVALID")
                require_current_execution_outline(session, case)
                record_answer(case, data.statement, data.expected_revision)
                case.session_data = {
                    **case.session_data,
                    "answers": [
                        *case.session_data["answers"][:-1],
                        {
                            **case.session_data["answers"][-1],
                            "actor_type": "candidate_invitation",
                        },
                    ],
                }
                if transcription:
                    answers = list(case.session_data["answers"])
                    original = transcription.detail["result"]
                    answers[-1] = {
                        **answers[-1],
                        "source_mode": original["source_mode"]
                        if voice_transcription
                        else answers[-1].get("source_mode", "manual"),
                        "audio_transcription": {
                            "task_id": transcription.id,
                            "text": original["text"],
                            "model": original["model"],
                            "source_mode": original["source_mode"],
                            "candidate_confirmed": voice_transcription is None,
                            "submission_mode": "automatic_voice"
                            if voice_transcription
                            else "manual_confirmation",
                            "edited": original["text"] != data.statement,
                        },
                    }
                    case.session_data = {**case.session_data, "answers": answers}
                invalidate_downstream(session, case, "D07")
                if case.session_data.get("decision_status") == "pending":
                    task, created = register_step(session, case.id, "followup", case.revision)
                    if created:
                        task.detail = {
                            **task.detail,
                            "knowledge_preview": case.session_data.get("knowledge_preview", False),
                            "actor_id": "candidate_invitation",
                            "organization_id": case.organization_id,
                        }
            if voice_transcription:
                state = case.session_data.get("preflight", {})
                case.session_data = {
                    **case.session_data,
                    "preflight": {
                        **state,
                        "voice_transcription_task_id": voice_transcription.id,
                        "source_mode": voice_transcription.detail["result"]["source_mode"],
                    },
                }
        except ValueError as error:
            if str(error) in OUTLINE_CONFLICTS:
                session.rollback()
                return conflict_response(request, str(error), allowed=OUTLINE_CONFLICTS)
            raise HTTPException(409, detail=str(error)) from None
        return Response(
            content=json.dumps(candidate_view(case)),
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )


@router.post("/calls/{case_id}/invitation")
def manage_invitation(case_id: str, data: InvitationInput, request: Request):
    from app.modules.outreach.invitations import issue_invitation, revoke_invitation

    identity = require_identity(request)
    with database_session(request) as session, session.begin():
        try:
            case = locked_case(session, case_id, identity["organization_id"], identity["user_id"])
            if case.revision != data.expected_revision:
                raise ValueError("VERSION_CONFLICT")
            if data.action == "issue":
                result = issue_invitation(case, data.lifetime_seconds)
            else:
                revoke_invitation(case)
                result = {"revoked": True}
        except LookupError:
            raise HTTPException(404) from None
        except ValueError as error:
            raise HTTPException(409, detail=str(error)) from None
        return Response(
            content=json.dumps({**result, "revision": case.revision}),
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )


@router.get("/calls/{case_id}/briefing")
def preflight_briefing(case_id: str, request: Request):
    import hashlib

    from app.modules.outreach.preflight import briefing_snapshot

    identity = require_identity(request)
    with database_session(request) as session:
        try:
            case = locked_case(session, case_id, identity["organization_id"], identity["user_id"])
        except LookupError:
            raise HTTPException(404) from None
        material = briefing_snapshot(case)
        return {
            "material": material,
            "sha256": hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest(),
        }


@router.post("/calls/{case_id}/preflight")
def update_preflight(case_id: str, data: PreflightInput, request: Request):
    from app.modules.outreach.preflight import (
        confirm_preflight,
        mock_briefing_email,
        record_interest,
    )

    identity = require_identity(request)
    with database_session(request) as session, session.begin():
        try:
            case = locked_case(session, case_id, identity["organization_id"], identity["user_id"])
            if case.revision != data.expected_revision:
                raise ValueError("VERSION_CONFLICT")
            if case.status in {"ended", "cancelled"} or case.stop_status != "none":
                raise ValueError("INTERVIEW_STOPPED")
            if data.action == "interest":
                if data.interested is None:
                    raise ValueError("INTEREST_REQUIRED")
                record_interest(case, data.interested, data.statement)
            elif data.action == "mock_email":
                if request.app.state.settings.environment != "development":
                    raise HTTPException(403)
                mock_briefing_email(case, data.email or "", data.statement, data.request_id or "")
            else:
                confirm_preflight(case, data.statement, data.material_sha256 or "")
        except LookupError:
            raise HTTPException(404) from None
        except ValueError as error:
            raise HTTPException(409, detail=str(error)) from None
        return case_view(case)
