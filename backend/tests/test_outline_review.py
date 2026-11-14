from types import SimpleNamespace

import pytest

from app.integrations.bailian import ModelUnavailable
from app.modules.outreach.outline_review import review_outline


@pytest.mark.parametrize("mode", ["pass", "compound_again", "scope", "budget"])
def test_revision_is_bounded_and_preserves_question_contract(monkeypatch, mode):
    from app.modules.outreach.interview import Outline
    from app.modules.outreach.outline_review import review_and_revise_outline

    outline = Outline.model_validate(
        {
            "questions": [
                {
                    "id": "Q1",
                    "dimension_id": "custom",
                    "question": "负责什么，如何完成？",
                    "evidence_target": "本人职责",
                    "planned_minutes": 26,
                }
            ]
        }
    )
    calls = []

    def model(settings, instruction, context):
        calls.append(context)
        if "outline" in context:
            revised = outline.model_dump()
            revised["questions"][0]["question"] = "你负责什么？"
            if mode == "scope":
                revised["questions"][0]["planned_minutes"] = 25
            return {"content": revised, "model": "fixture", "usage": None}
        return {
            "content": {
                "checks": [
                    {
                        "question_ref": "Q1",
                        "single_goal": len(calls) == 3 and mode != "compound_again",
                        "reason": "测试复核",
                    }
                ]
            },
            "model": "fixture",
            "usage": None,
        }

    reservations = []

    def reserve():
        reservations.append(True)
        if mode == "budget":
            raise ModelUnavailable("MODEL_REQUEST_BUDGET_EXCEEDED")

    monkeypatch.setattr("app.modules.outreach.outline_review.generate_json", model)
    if mode == "pass":
        revised, receipt = review_and_revise_outline(None, outline, reserve)
        assert revised.questions[0].question == "你负责什么？"
        assert receipt["revision"]["attempts"] == 1
        assert outline.questions[0].question == "负责什么，如何完成？"
    else:
        with pytest.raises(ModelUnavailable):
            review_and_revise_outline(None, outline, reserve)
    assert len(reservations) == 1
    assert len(calls) == {"pass": 3, "compound_again": 3, "scope": 2, "budget": 1}[mode]


@pytest.mark.parametrize("mode", ["pass", "compound", "missing", "duplicate"])
def test_review_requires_every_question_and_rejects_compound(monkeypatch, mode):
    outline = SimpleNamespace(
        questions=[
            SimpleNamespace(
                id="Q1",
                question="负责什么？",
                conditional_followups=[SimpleNamespace(question="采取什么行动？")],
            )
        ]
    )
    checks = [
        {"question_ref": ref, "single_goal": True, "reason": "单一目标"}
        for ref in ["Q1", "Q1/followup/1"]
    ]
    if mode == "compound":
        checks[0]["single_goal"] = False
    elif mode == "missing":
        checks.pop()
    elif mode == "duplicate":
        checks[1]["question_ref"] = "Q1"
    monkeypatch.setattr(
        "app.modules.outreach.outline_review.generate_json",
        lambda *args: {
            "content": {"checks": checks},
            "model": "fixture",
            "usage": None,
        },
    )
    if mode == "pass":
        assert len(review_outline(None, outline)["checks"]) == 2
    else:
        with pytest.raises(ModelUnavailable):
            review_outline(None, outline)
