from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.modules.outreach.answers import record_answer
from app.modules.outreach.followup_worker import execute_followup
from app.modules.outreach.handoff import question_execution_ref
from app.modules.outreach.models import OutreachArtifact, OutreachCase
from app.modules.outreach.postprocessing import schedule_postprocessing
from app.modules.outreach.processing_permissions import (
    finalize_interview_session,
    record_processing_permission,
)
from app.modules.outreach.steps import register_step


def test_candidate_permission_receipts_produce_session_and_withdrawal_invalidates():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db, db.begin():
        case = OutreachCase(
            id="c",
            organization_id="org",
            owner_id="owner",
            application_id="app",
            candidate_id="person",
            job_id="job",
            snapshot={"fixture_only": True},
            session_data={},
            status="in_progress",
            stop_status="none",
            revision=1,
        )
        db.add(case)
        outline = OutreachArtifact(
            id="outline",
            case_id="c",
            type="D07",
            version=1,
            content={},
            provenance={"job_interview_standard": {"standard": {"version": 1}}},
            input_refs=[],
        )
        db.add(outline)
        db.flush()
        for purpose in ["formal_interview", "transcription", "extraction", "evaluation"]:
            record_processing_permission(db, case, purpose, True, case.revision)
        case.session_data = {
            **case.session_data,
            "current_question": {
                "id": "Q1",
                "question": "您还有什么想补充的吗？",
                "execution_ref": question_execution_ref(outline, "Q1"),
            },
        }
        record_answer(case, "没有补充，谢谢", case.revision)
        answers = case.session_data["answers"]
        case.session_data = {
            **case.session_data,
            "answers": [{**answers[0], "actor_type": "candidate_invitation"}],
            "outline_id": outline.id,
            "job_interview_standard": outline.provenance["job_interview_standard"],
        }
        task, _ = register_step(db, case.id, "followup", case.revision)
        task_id = task.id
    execute_followup(engine, Settings(), task_id)
    with Session(engine) as db, db.begin():
        case = db.get(OutreachCase, "c")
        assert case.status == "ended"
        assert case.stop_status == "none"
        assert schedule_postprocessing(db, case_id=case.id) == 1
        package = case.session_data["a06_session"]
        assert package["status"] == "COMPLETED"
        assert package["answer_turns"][0]["text"] == "没有补充，谢谢"
        assert package["answer_turns"][0]["source_type"] == "CANDIDATE_TEXT"
        assert package["answer_turns"][0]["question_text"] == "您还有什么想补充的吗？"
        assert package["answer_turns"][0]["transcription_ref"] is None
        assert package["answer_source_modes"] == ["manual"]
        assert package["opportunity_interest"] == "UNKNOWN"
        assert package["executed_outline"] == {"id": "outline", "version": 1}
        original_data = case.session_data
        case.session_data = {
            **original_data,
            "termination_reason": None,
            "attempts": [{"status": "interrupted", "source_mode": "mock"}],
        }
        interrupted = finalize_interview_session(db, case)
        assert interrupted["status"] == "INTERRUPTED"
        assert interrupted["call_attempt_source_mode"] == "mock"
        case.session_data = original_data
        artifact = OutreachArtifact(
            id="minutes",
            case_id="c",
            type="D08",
            version=1,
            content={},
            provenance={},
            input_refs=[],
        )
        db.add(artifact)
        db.flush()
        record_processing_permission(db, case, "extraction", False, case.revision)
        assert not artifact.valid
        assert case.session_data["a06_session"] is None
        assert case.session_data["processing_permissions"]["extraction"]["status"] == "WITHDRAWN"
