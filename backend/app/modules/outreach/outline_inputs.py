"""Validate A10's six upstream artifacts before spending a model request."""

import time
from copy import deepcopy

from app.integrations.bailian import ModelUnavailable
from app.modules.outreach.job_standard import JobInterviewStandard


def outline_handoff(case, outline, dimensions, *, preview):
    reasons = []
    if case.snapshot.get("fixture_only"):
        reasons.append("虚构上游，仅供隔离流程验收，不可作为真实外呼准备。")
    if preview:
        reasons.append("使用未审核知识预览，须完成专业审核后用于正式业务。")
    if not case.session_data.get("job_interview_standard"):
        reasons.append("仅使用演示维度，尚无已确认的岗位面试标准。")
    research = case.session_data.get("upstream_content", {}).get("D04", {})
    if research.get("gaps"):
        reasons.append("D04 记录了研究缺口，请复核是否影响核心考核。")
    rows = []
    for dimension in dimensions:
        questions = [q for q in outline.questions if q.dimension_id == dimension["id"]]
        rows.append(
            {
                "dimension_id": dimension["id"],
                "dimension_name": dimension.get("label"),
                "weight_percent": dimension.get("weight_percent"),
                "indicator": dimension.get("indicators"),
                "question_ids": [q.id for q in questions],
                "evidence_targets": [q.evidence_target for q in questions],
                "planned_minutes": sum(q.planned_minutes for q in questions),
                "coverage_status": "PLANNED" if questions else "MISSING",
            }
        )
    missing = any(row["coverage_status"] == "MISSING" for row in rows)
    if missing:
        reasons.append("存在未安排主问题的能力维度。")
    return {
        "readiness": "BLOCKED" if missing else "READY_WITH_LIMITATIONS" if reasons else "READY",
        "readiness_reasons": reasons,
        "dimension_coverage": rows,
        "planned_total_minutes": 35,
        "time_plan": {
            "opening_consent": 2,
            "competency": 26,
            "candidate_questions": 4,
            "closing": 3,
        },
        "handoff_to": "A06",
    }


def outline_dimensions(case):
    binding = case.session_data.get("job_interview_standard")
    if binding:
        try:
            standard = JobInterviewStandard.model_validate(binding["standard"])
        except (ValueError, KeyError, TypeError) as error:
            raise ModelUnavailable("STANDARD_INVALID") from error
        if standard.status != "confirmed" or standard.job_id != case.job_id:
            raise ModelUnavailable("STANDARD_CONFIRMATION_REQUIRED")
        return [dimension.model_dump(mode="json") for dimension in standard.dimensions]
    if not case.snapshot.get("fixture_only"):
        raise ModelUnavailable("STANDARD_CONFIRMATION_REQUIRED")
    return [
        {"id": "responsibility", "label": "职责（虚构演示）"},
        {"id": "results", "label": "成果（虚构演示）"},
    ]


def _check_current_outline(case, outline):
    data = case.session_data
    fixture = case.snapshot.get("fixture_only")
    if data.get("outline_requires_regeneration"):
        raise ValueError("OUTLINE_REGENERATION_REQUIRED")
    if outline is None and fixture and not data.get("outline_id"):
        return
    if (
        outline is None
        or outline.case_id != case.id
        or outline.type != "D07"
        or not outline.valid
        or outline.id != data.get("outline_id")
        or outline.provenance.get("job_interview_standard") != data.get("job_interview_standard")
    ):
        raise ValueError("OUTLINE_REGENERATION_REQUIRED")
    readiness = outline.content.get("readiness")
    if readiness == "BLOCKED":
        raise ValueError("OUTLINE_BLOCKED")
    if fixture:
        return
    try:
        outline_inputs(case)
        outline_dimensions(case)
    except ModelUnavailable as error:
        raise ValueError("OUTLINE_REGENERATION_REQUIRED") from error
    refs = case.snapshot["artifact_refs"]
    if any(
        {"kind": "artifact", "id": refs[key]["artifact_id"], "version": refs[key]["version"]}
        not in outline.input_refs
        for key in ("D01", "D02", "D03", "D04", "D05", "D06")
    ):
        raise ValueError("OUTLINE_REGENERATION_REQUIRED")


def require_execution_outline(case, outline):
    """Check the current preparation version before entering or continuing A06."""
    _check_current_outline(case, outline)
    if case.snapshot.get("fixture_only") or outline.content.get("readiness") == "READY":
        return
    review = case.session_data.get("outline_readiness_review") or {}
    if (
        outline.content.get("readiness") != "READY_WITH_LIMITATIONS"
        or review.get("outline_id") != outline.id
        or review.get("outline_version") != outline.version
        or review.get("limitations") != outline.content.get("readiness_reasons")
        or not review.get("reviewer_id")
    ):
        raise ValueError("OUTLINE_READINESS_REVIEW_REQUIRED")


def approve_outline_limitations(
    case, outline, *, expected_revision, expected_version, reviewer_id, rationale
):
    """Persist an authorized review against exactly one current D07 version."""
    if case.revision != expected_revision:
        raise ValueError("VERSION_CONFLICT")
    if case.status in {"ended", "cancelled"} or case.stop_status != "none":
        raise ValueError("INTERVIEW_STOPPED")
    _check_current_outline(case, outline)
    if outline is None or outline.version != expected_version:
        raise ValueError("OUTLINE_REGENERATION_REQUIRED")
    if outline.content.get("readiness") != "READY_WITH_LIMITATIONS":
        raise ValueError("OUTLINE_LIMITATIONS_REVIEW_NOT_APPLICABLE")
    limitations = outline.content.get("readiness_reasons")
    if not reviewer_id or not rationale.strip() or not limitations:
        raise ValueError("OUTLINE_LIMITATIONS_REVIEW_INVALID")
    receipt = {
        "outline_id": outline.id,
        "outline_version": outline.version,
        "limitations": deepcopy(limitations),
        "reviewer_id": reviewer_id,
        "rationale": rationale.strip(),
        "recorded_at": time.time(),
    }
    case.session_data = {**case.session_data, "outline_readiness_review": receipt}
    case.revision += 1
    return receipt


def outline_inputs(case):
    if case.session_data.get("upstream_invalidated"):
        raise ModelUnavailable("UPSTREAM_REVIEW_REQUIRED")
    content = case.session_data.get("upstream_content")
    refs = case.snapshot.get("artifact_refs", {})
    required = [f"D{i:02}" for i in range(1, 7)]
    if not isinstance(content, dict) or any(
        not isinstance(content.get(key), dict) or not content[key] for key in required
    ):
        raise ModelUnavailable("UPSTREAM_CONTENT_NOT_READY")
    if any(
        not isinstance(refs.get(key), dict)
        or not refs[key].get("artifact_id")
        or type(refs[key].get("version")) is not int
        or refs[key]["version"] < 1
        for key in required
    ):
        raise ModelUnavailable("UPSTREAM_VERSION_NOT_READY")
    if (
        case.snapshot.get("screening_result") != "passed"
        or content["D06"].get("conclusion") != "passed"
    ):
        raise ModelUnavailable("SCREENING_NOT_ELIGIBLE")
    for key in required:
        item = content[key]
        ref = refs[key]
        if ("artifact_id" in item and item["artifact_id"] != ref["artifact_id"]) or (
            "artifact_version" in item
            and (
                type(item["artifact_version"]) is not int
                or item["artifact_version"] != ref["version"]
            )
        ):
            raise ModelUnavailable("UPSTREAM_CONTENT_VERSION_MISMATCH")
        for field, expected in (
            ("job_id", case.job_id),
            ("organization_id", case.organization_id),
        ):
            if field in item and item[field] != expected:
                raise ModelUnavailable("UPSTREAM_IDENTITY_MISMATCH")
        if key in {"D03", "D04", "D05", "D06"} and "candidate_id" in item:
            if item["candidate_id"] != case.candidate_id:
                raise ModelUnavailable("UPSTREAM_IDENTITY_MISMATCH")
    return content
