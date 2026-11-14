from pathlib import Path

import pytest
from pydantic import ValidationError

from app.modules.outreach.evaluation import (
    EvaluationTemplate,
    EvidenceAssessment,
    validate_evaluation,
)


def template():
    return EvaluationTemplate.model_validate_json(
        (Path(__file__).parents[1] / "config/demo-evaluation.v1.json").read_text(encoding="utf8")
    )


@pytest.mark.parametrize("score,conclusion", [(4, "recommended"), (1, "rejected")])
def test_demo_decisions(score, conclusion):
    assessments = [
        EvidenceAssessment(
            dimension_id=d.id, score=score, evidence_ids=["answer-1"], reason="虚构验证"
        )
        for d in template().dimensions
    ]
    result = validate_evaluation(
        template(), assessments, {"answer-1": "虚构候选人实际输入"}, fixture_only=True
    )
    assert result["conclusion"] == conclusion
    assert result["demo_rules"]


def test_missing_evidence_is_unassessed_and_demo_is_isolated():
    assessments = [
        EvidenceAssessment(dimension_id=d.id, score=5, reason="无证据")
        for d in template().dimensions
    ]
    result = validate_evaluation(template(), assessments, {}, fixture_only=True)
    assert result["conclusion"] == "insufficient"
    assert result["score"] is None
    assert all(d["score"] is None for d in result["dimensions"])
    with pytest.raises(ValueError, match="real candidates"):
        validate_evaluation(template(), assessments, {}, fixture_only=False)
    with pytest.raises(ValidationError):
        EvidenceAssessment(dimension_id="results", score=11, reason="invalid")


def test_unknown_evidence_rejected():
    assessments = [
        EvidenceAssessment(dimension_id=d.id, score=4, evidence_ids=["invented"], reason="invalid")
        for d in template().dimensions
    ]
    with pytest.raises(ValueError, match="Unknown"):
        validate_evaluation(template(), assessments, {}, fixture_only=True)


@pytest.mark.parametrize("fault", [None, "band", "reason", "missing_ev", "unknown_ev", "dimension"])
def test_formal_score_requires_matching_anchor_and_dimension_fact(fault):
    bound = template().model_dump()
    bound.update(status="approved", score_scale="1-10", threshold=7)
    for dimension in bound["dimensions"]:
        dimension["scoring_anchors"] = {
            band: "虚构岗位行为锚点" for band in ["1-2", "3-4", "5-6", "7-8", "9-10"]
        }
    configured = EvaluationTemplate.model_validate(bound)
    assessments = [
        EvidenceAssessment(
            dimension_id=d.id,
            score=7,
            evidence_ids=["a1"],
            reason="本人行动对应岗位指标",
            fact_evidence_ids=["EV1"],
            matched_anchor_band="7-8",
            anchor_rationale="EV1说明本人执行行为，达到本岗位7-8档，复杂场景成果仍缺",
        )
        for d in configured.dimensions
    ]
    facts = [
        {
            "evidence_id": "EV1",
            "answer_id": "a1",
            "d02_dimension_ids": [d.id for d in configured.dimensions],
        }
    ]
    if fault == "band":
        assessments[0].matched_anchor_band = "9-10"
    elif fault == "reason":
        assessments[0].anchor_rationale = " "
    elif fault == "missing_ev":
        assessments[0].fact_evidence_ids = []
    elif fault == "unknown_ev":
        assessments[0].fact_evidence_ids = ["EV99"]
    elif fault == "dimension":
        facts[0]["d02_dimension_ids"] = []
    if fault:
        with pytest.raises(ValueError, match="SCORING_"):
            validate_evaluation(
                configured,
                assessments,
                {"a1": "虚构原话"},
                fixture_only=False,
                evidence_items=facts,
            )
        return
    result = validate_evaluation(
        configured, assessments, {"a1": "虚构原话"}, fixture_only=False, evidence_items=facts
    )
    assert result["total_score"] == 70
    assert result["summary"]["scored_dimension_count"] == len(configured.dimensions)
    assert result["dimensions"][0]["anchor_basis_status"] == "RECORDED"
    assert result["dimensions"][0]["matched_anchor_text"] == "虚构岗位行为锚点"
