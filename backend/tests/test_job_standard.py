from decimal import Decimal

import pytest

from app.modules.outreach.job_standard import JobInterviewStandard, calculate_standard_score


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
