from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.outreach.evaluation import EvidenceAssessment, validate_evaluation
from app.modules.outreach.job_standard import (
    JobInterviewStandard,
    calculate_standard_score,
    evaluation_template_from_standard,
)


def standard():
    return JobInterviewStandard(
        job_id="fixture",
        version=1,
        status="confirmed",
        confirmed_by="reviewer",
        dimensions=[
            {
                "id": key,
                "label": key,
                "indicators": "虚构岗位指标",
                "weight_percent": weight,
                "source_refs": ["fixture-job-paragraph"],
                "anchors": {
                    band: "虚构的岗位行为锚点" for band in ["1-2", "3-4", "5-6", "7-8", "9-10"]
                },
            }
            for key, weight in [("one", 20), ("two", 80)]
        ],
    )


def test_evaluation_binding_rejects_changed_standard_fields():
    from app.modules.outreach.templates import validate_standard_template

    configured = evaluation_template_from_standard(
        standard(), threshold=8, report_template_version=1
    )
    case = SimpleNamespace(
        session_data={"job_interview_standard": {"standard": standard().model_dump()}}
    )
    validate_standard_template(case, configured, "D09")
    for field, value in [("score_scale", "0-5"), ("version", 2), ("status", "demo")]:
        with pytest.raises(ValueError, match="EVALUATION_STANDARD_MISMATCH"):
            validate_standard_template(case, configured.model_copy(update={field: value}), "D09")
    changed = configured.model_copy(deep=True)
    changed.dimensions[0].scoring_anchors["7-8"] = "different anchor"
    with pytest.raises(ValueError, match="EVALUATION_STANDARD_MISMATCH"):
        validate_standard_template(case, changed, "D09")


def test_ten_point_weighted_score_and_missing_coverage():
    template = standard()
    result = calculate_standard_score(template, {"one": 8, "two": 10})
    assert result["dimensions"][0]["weighted_score"] == Decimal(16)
    assert result["total_score"] == Decimal(96)
    incomplete = calculate_standard_score(template, {"one": 8, "two": None})
    assert incomplete["total_score"] is None and incomplete["scored_weight_percent"] == 20
    assert incomplete["dimensions"][1]["weighted_score"] is None
    with pytest.raises(ValueError):
        calculate_standard_score(template, {"one": 0, "two": 10})
    draft = template.model_copy(update={"status": "draft", "confirmed_by": None})
    with pytest.raises(ValueError, match="CONFIRMATION"):
        calculate_standard_score(draft, {"one": 8, "two": 10})


def test_confirmed_standard_adapts_to_evaluation_without_rescaling():
    configured = evaluation_template_from_standard(
        standard(), threshold=8, report_template_version=1
    )
    assessments = [
        EvidenceAssessment(dimension_id=key, score=score, evidence_ids=["a1"], reason="自述")
        for key, score in [("one", 8), ("two", 10)]
    ]
    result = validate_evaluation(configured, assessments, {"a1": "实际回答"}, fixture_only=True)
    assert result["score"] == pytest.approx(9.6)
    assert result["score_scale"] == "1-10"
    assert result["total_score"] == pytest.approx(96)
    assert result["scored_weight_percent"] == 100
    assert result["dimensions"][0]["weighted_score"] == 16
    assert result["conclusion"] == "recommended"
    assessments[1].evidence_ids = []
    missing = validate_evaluation(configured, assessments, {"a1": "实际回答"}, fixture_only=True)
    assert missing["score"] is None and missing["total_score"] is None
    assert missing["scored_weight_percent"] == 20
    assert missing["dimensions"][0]["weighted_score"] == 16
    assessments[1].evidence_ids = ["a1"]
    assessments[0].score = 8.5
    with pytest.raises(ValueError, match="configured scale"):
        validate_evaluation(configured, assessments, {"a1": "实际回答"}, fixture_only=True)
