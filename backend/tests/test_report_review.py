import pytest

from app.integrations.bailian import ModelUnavailable
from app.modules.outreach.report_review import review_report_claims


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
