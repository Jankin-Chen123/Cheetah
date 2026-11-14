"""Describe available preparation references without inventing execution or consent."""

from app.modules.outreach.interview import termination_reason
from app.modules.outreach.models import OutreachArtifact
from app.modules.outreach.outline_inputs import require_execution_outline


def question_execution_ref(outline, question_id, *, parent_question_id=None):
    """Stamp the server-selected question before a candidate answer exists."""
    return {
        "outline_ref": {"id": outline.id, "version": outline.version},
        "standard_binding": outline.provenance.get("job_interview_standard"),
        "question_id": question_id,
        "parent_question_id": parent_question_id,
    }


def require_extraction_session(session, case):
    """Validate a persisted execution receipt; preparation and interest are not consent."""
    answers = case.session_data.get("answers", [])
    if answers and termination_reason(answers[-1]["text"], 0, 0) == "candidate_requested_stop":
        raise ValueError("A06_STOP_COMMAND_IN_ANSWERS")
    if case.session_data.get("processing_permissions"):
        from app.modules.outreach.processing_permissions import require_processing_permission

        for purpose in ("formal_interview", "transcription", "extraction", "evaluation"):
            require_processing_permission(case, purpose)
    package = case.session_data.get("a06_session")
    if not package:
        if case.snapshot.get("fixture_only") and not case.session_data.get(
            "processing_permissions"
        ):
            return None
        raise ValueError("A06_SESSION_REQUIRED")
    if any(
        package.get(key) != value
        for key, value in {
            "organization_id": case.organization_id,
            "job_id": case.job_id,
            "candidate_id": case.candidate_id,
            "case_id": case.id,
        }.items()
    ):
        raise ValueError("A06_SESSION_IDENTITY_MISMATCH")
    if not package.get("session_id") or package.get("interview_mode") != "FORMAL_INTERVIEW":
        raise ValueError("A06_FORMAL_INTERVIEW_REQUIRED")
    if package.get("status") not in {"COMPLETED", "PARTIAL", "INTERRUPTED"}:
        raise ValueError("A06_SESSION_NOT_FINISHED")
    permissions = package.get("permissions", {})
    current_permissions = case.session_data.get("processing_permissions", {})
    for purpose in ("formal_interview", "transcription", "extraction", "evaluation"):
        receipt = permissions.get(purpose, {})
        if (
            receipt.get("status") != "AUTHORIZED"
            or not receipt.get("receipt_id")
            or not receipt.get("recorded_at")
            or receipt != current_permissions.get(purpose)
        ):
            raise ValueError("A06_PROCESSING_PERMISSION_REQUIRED")
    ref = package.get("executed_outline") or {}
    outline = session.get(OutreachArtifact, ref.get("id")) if ref.get("id") else None
    if (
        outline is None
        or outline.case_id != case.id
        or outline.type != "D07"
        or not outline.valid
        or outline.version != ref.get("version")
    ):
        raise ValueError("A06_EXECUTED_OUTLINE_INVALID")
    if not case.snapshot.get("fixture_only") or case.session_data.get("outline_id"):
        require_execution_outline(case, outline)
    review = package.get("outline_readiness_review")
    if (
        review is not None
        or (
            not case.snapshot.get("fixture_only")
            and outline.content.get("readiness") == "READY_WITH_LIMITATIONS"
        )
    ) and (not review or review != case.session_data.get("outline_readiness_review")):
        raise ValueError("A06_OUTLINE_READINESS_REVIEW_MISMATCH")
    standard = outline.provenance.get("job_interview_standard")
    if not standard or package.get("executed_standard") != standard:
        raise ValueError("A06_EXECUTED_STANDARD_MISMATCH")
    turns = package.get("answer_turns", [])
    answer_ids = [answer["id"] for answer in answers]
    if (
        not answers
        or len(set(answer_ids)) != len(answer_ids)
        or [turn.get("answer_id") for turn in turns] != answer_ids
    ):
        raise ValueError("A06_TURN_COVERAGE_INVALID")
    by_answer = {answer["id"]: answer for answer in answers}
    turn_ids = set()
    for turn in turns:
        answer = by_answer.get(turn.get("answer_id"))
        transcription = (answer or {}).get("audio_transcription") or {}
        if (
            answer is None
            or turn.get("text") != answer["text"]
            or turn.get("speaker") != "candidate"
            or not turn.get("turn_id")
            or turn["turn_id"] in turn_ids
            or turn.get("question_id") != answer.get("question", {}).get("id")
            or turn.get("outline_ref") != ref
            or turn.get("answer_version") != answer.get("version", 1)
            or turn.get("recorded_at") != answer.get("recorded_at")
            or turn.get("source_mode") != answer.get("source_mode")
            or turn.get("transcription_ref") != transcription.get("task_id")
            or turn.get("transcription_source_mode") != transcription.get("source_mode")
            or turn["turn_id"] != answer.get("turn_id")
            or turn.get("question_text", answer["question"].get("question"))
            != answer["question"].get("question")
            or turn.get("dimension_id", answer["question"].get("dimension_id"))
            != answer["question"].get("dimension_id")
        ):
            raise ValueError("A06_TURN_PROVENANCE_INVALID")
        execution = answer.get("execution_ref") or {}
        if (
            execution.get("outline_ref") != ref
            or execution.get("standard_binding") != standard
            or execution.get("question_id") != turn["question_id"]
            or execution.get("parent_question_id") != turn.get("parent_question_id")
            or turn.get("standard_binding", standard) != standard
        ):
            raise ValueError("A06_QUESTION_EXECUTION_REQUIRED")
        turn_ids.add(turn["turn_id"])
    return package


def preparation_metadata(session, case):
    outline_id = case.session_data.get("outline_id")
    outline = session.get(OutreachArtifact, outline_id) if outline_id else None
    limitations = []
    refs = {}
    if outline is None or outline.case_id != case.id or outline.type != "D07":
        limitations.append("未找到同案例的D07准备稿引用，无法核验执行提纲版本。")
    else:
        refs["D07"] = {"id": outline.id, "version": outline.version, "valid": outline.valid}
        binding = outline.provenance.get("job_interview_standard")
        if binding:
            refs["D02"] = binding
        else:
            limitations.append("D07未记录已确认D02快照，不能推定执行标准版本。")
        if not case.session_data.get("a06_session"):
            limitations.append("准备稿引用不证明每条回答执行了该版本；仍需逐轮题号版本记录。")
    if not case.session_data.get("a06_session"):
        limitations.append("当前仅依据已存回答提取；未提供完整A06会话包与逐项处理许可回执。")
    answers = case.session_data.get("answers", [])
    planned = outline.content.get("questions", []) if outline and outline.case_id == case.id else []
    question_coverage = []
    for question in planned:
        direct = [a for a in answers if a.get("question", {}).get("id") == question.get("id")]
        followups = [
            a
            for a in answers
            if (a.get("execution_ref") or {}).get("parent_question_id") == question.get("id")
        ]
        question_coverage.append(
            {
                "question_id": question.get("id"),
                "dimension_id": question.get("dimension_id"),
                "execution_status": "ANSWER_RECORDED" if direct else "NO_ANSWER_RECORDED",
                "answer_ids": [a["id"] for a in direct],
                "followup_answer_ids": [a["id"] for a in followups],
                "turn_ids": [a["turn_id"] for a in [*direct, *followups] if a.get("turn_id")],
                "note": "已保存回答不证明音频已播放；未记录回答的原因未知。",
            }
        )
    return {
        "preparation_refs": refs,
        "extraction_limitations": limitations,
        "question_execution_coverage": question_coverage,
    }
