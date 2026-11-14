from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.modules.outreach.handoff import require_extraction_session


@pytest.mark.parametrize(
    "fault", [None, "identity", "intent", "permission", "version", "turn", "correction"]
)
def test_formal_extraction_requires_execution_and_independent_permissions(fault):
    standard = {"standard": {"version": 1}}
    outline = SimpleNamespace(
        case_id="c",
        type="D07",
        valid=True,
        version=1,
        provenance={"job_interview_standard": standard},
    )
    ref = {"id": "outline", "version": 1}
    package = {
        "organization_id": "org",
        "job_id": "job",
        "candidate_id": "person",
        "case_id": "c",
        "session_id": "session",
        "interview_mode": "FORMAL_INTERVIEW",
        "status": "COMPLETED",
        "permissions": {
            purpose: {"status": "AUTHORIZED", "receipt_id": purpose, "recorded_at": 1}
            for purpose in ["transcription", "extraction", "evaluation"]
        },
        "executed_outline": ref,
        "executed_standard": standard,
        "answer_turns": [
            {
                "answer_id": "a",
                "answer_version": 1,
                "text": "原话",
                "speaker": "candidate",
                "turn_id": "t",
                "question_id": "q",
                "outline_ref": deepcopy(ref),
            }
        ],
    }
    case = SimpleNamespace(
        id="c",
        organization_id="org",
        job_id="job",
        candidate_id="person",
        snapshot={},
        session_data={
            "a06_session": package,
            "answers": [{"id": "a", "text": "原话", "question": {"id": "q"}}],
        },
    )
    if fault == "identity":
        package["candidate_id"] = "other"
    elif fault == "intent":
        package["interview_mode"] = "INFO_FIRST"
    elif fault == "permission":
        package["permissions"]["extraction"]["status"] = "WITHDRAWN"
    elif fault == "version":
        package["executed_outline"]["version"] = 2
    elif fault == "turn":
        package["answer_turns"][0]["speaker"] = "interviewer"
    elif fault == "correction":
        case.session_data["answers"][0]["text"] = "已更正"
    session = SimpleNamespace(get=lambda *args: outline)
    case.session_data["answers"][0]["execution_ref"] = {
        "outline_ref": {"id": "outline", "version": 1},
        "standard_binding": standard,
        "question_id": "q",
    }
    if fault:
        with pytest.raises(ValueError, match="A06_"):
            require_extraction_session(session, case)
    else:
        assert require_extraction_session(session, case) == package


def test_fixture_exception_does_not_enable_unrecorded_formal_interview():
    case = SimpleNamespace(snapshot={}, session_data={})
    with pytest.raises(ValueError, match="A06_SESSION_REQUIRED"):
        require_extraction_session(None, case)
    case.snapshot = {"fixture_only": True}
    assert require_extraction_session(None, case) is None
