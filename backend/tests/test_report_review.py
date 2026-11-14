import pytest

from app.integrations.bailian import ModelUnavailable
from app.modules.outreach.report_review import review_report_claims


def test_summary_and_job_relevance_are_both_reviewed(monkeypatch):
    from app.modules.outreach.recommendation import RecommendationOutput

    output = RecommendationOutput.model_validate(
        {
            "summary": {"text": "候选人自述负责访谈", "answer_ids": ["a1"]},
            "match_highlights": [
                {
                    "text": "候选人自述执行访谈",
                    "answer_ids": ["a1"],
                    "job_relevance": "不能据此证明全面研究能力",
                }
            ],
        }
    )

    def model(settings, instruction, context):
        assert len(context["items"]) == 2
        assert context["items"][0]["claim"] == "候选人自述负责访谈"
        assert "不能据此证明全面研究能力" in context["items"][1]["claim"]
        return {
            "content": {
                "checks": [
                    {"claim_index": 0, "supported": False, "reason": "摘要不支持"},
                    {"claim_index": 1, "supported": True, "reason": "亮点支持"},
                ]
            },
            "model": "fixture",
        }

    monkeypatch.setattr("app.modules.outreach.report_review.generate_json", model)
    with pytest.raises(ModelUnavailable, match="REPORT_CLAIM_UNSUPPORTED"):
        review_report_claims(
            None,
            [c.model_dump() for c in output.evidence_claims()],
            [{"id": "a1", "text": "我执行访谈"}],
        )


@pytest.mark.parametrize("mode", ["supported", "unsupported", "missing", "duplicate"])
def test_report_review_requires_complete_support(monkeypatch, mode):
    checks = [{"claim_index": 0, "supported": mode != "unsupported", "reason": "虚构核查"}]
    if mode == "missing":
        checks = []
    elif mode == "duplicate":
        checks *= 2
    monkeypatch.setattr(
        "app.modules.outreach.report_review.generate_json",
        lambda *args: {
            "content": {"checks": checks},
            "model": "fixture",
            "usage": None,
        },
    )
    claims = [{"text": "候选人自述负责访谈", "answer_ids": ["a1"]}]
    answers = [{"id": "a1", "text": "我负责访谈"}]
    if mode == "supported":
        assert review_report_claims(None, claims, answers)["checks"][0]["supported"]
    else:
        with pytest.raises(ModelUnavailable):
            review_report_claims(None, claims, answers)
