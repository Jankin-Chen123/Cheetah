from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.modules.outreach.answers import record_answer
from app.modules.outreach.handoff import question_execution_ref
from app.modules.outreach.models import OutreachArtifact, OutreachCase
from app.modules.outreach.postprocessing import schedule_postprocessing
from app.modules.outreach.processing_permissions import record_processing_permission


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
                "question": "你负责哪项工作？",
                "execution_ref": question_execution_ref(outline, "Q1"),
            },
        }
        record_answer(case, "虚构回答：我负责访谈。", case.revision)
        answers = case.session_data["answers"]
        case.session_data = {
            **case.session_data,
            "answers": [{**answers[0], "actor_type": "candidate_invitation"}],
            "termination_reason": "interview_completed",
        }
        case.status = "ended"
        case.stop_status = "confirmed"
        assert schedule_postprocessing(db, case_id=case.id) == 1
        package = case.session_data["a06_session"]
        assert package["status"] == "COMPLETED"
        assert package["answer_turns"][0]["text"] == "虚构回答：我负责访谈。"
        assert package["answer_turns"][0]["source_type"] == "CANDIDATE_TEXT"
        assert package["executed_outline"] == {"id": "outline", "version": 1}
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
