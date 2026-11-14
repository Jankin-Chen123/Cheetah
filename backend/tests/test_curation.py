import pytest
from pydantic import ValidationError

from app.modules.outreach.curation import CuratedMethod, curate
from app.modules.outreach.knowledge import MethodEntry


def test_curation_requires_complete_method_and_keeps_source():
    with pytest.raises(ValidationError):
        CuratedMethod.model_validate({"topic": "incomplete"})
    method = CuratedMethod(
        topic="虚构方法",
        dimensions=["responsibility"],
        tags=["responsibility"],
        trigger_conditions=["个人贡献未知"],
        question_examples=["请描述个人行动？"],
        followup_strategy="核实职责边界",
        stop_conditions=["证据完整或候选人停止"],
        exceptions=["拒答保留未知"],
    )
    entry = MethodEntry(
        content={
            "source_text": "虚构原文",
            "source_paragraphs": [2, 4],
            "generator": {"kind": "manual"},
            "method_version": 3,
        },
        review_status="pending",
    )
    curate(entry, method, "reviewer", True)
    assert entry.review_status == "approved"
    assert entry.content["source_text"] == "虚构原文"
    assert entry.content["source_paragraphs"] == [2, 4]
    assert entry.content["generator"] == {"kind": "manual"}
    assert entry.content["method_version"] == 4
    with pytest.raises(ValueError, match="immutable"):
        curate(entry, method, "reviewer", True)
    other = MethodEntry(content={"source_text": "虚构原文"}, review_status="pending")
    with pytest.raises(ValueError, match="conflicts"):
        curate(other, method.model_copy(update={"conflicts": ["待核实冲突"]}), "reviewer", True)
