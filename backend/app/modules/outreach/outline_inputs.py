"""Validate A10's six upstream artifacts before spending a model request."""

from app.integrations.bailian import ModelUnavailable
from app.modules.outreach.job_standard import JobInterviewStandard


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


def outline_inputs(case):
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
