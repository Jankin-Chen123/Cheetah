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
