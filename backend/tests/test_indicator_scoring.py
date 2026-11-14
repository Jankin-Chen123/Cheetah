import pytest

from app.modules.outreach.evaluation import EvidenceAssessment
from app.modules.outreach.recommendation import validate_indicator_scoring


@pytest.mark.parametrize("score", [None, 1, 7, 10])
def test_insufficient_indicator_cannot_become_low_or_high_score(score):
    assessment = EvidenceAssessment(
        dimension_id="research", score=score, evidence_ids=["a1"], reason="虚构依据"
    )
    rows = [{"dimension_id": "research", "evidence_sufficiency": "INSUFFICIENT"}]
    if score is None:
        validate_indicator_scoring([assessment], rows)
    else:
        with pytest.raises(ValueError, match="REQUIRES_REVIEW"):
            validate_indicator_scoring([assessment], rows)


def test_sufficient_indicator_does_not_force_a_score():
    assessment = EvidenceAssessment(
        dimension_id="research", score=None, evidence_ids=[], reason="尚需核实归因"
    )
    validate_indicator_scoring(
        [assessment], [{"dimension_id": "research", "evidence_sufficiency": "SUFFICIENT"}]
    )
