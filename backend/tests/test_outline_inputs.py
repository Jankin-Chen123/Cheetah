from types import SimpleNamespace

import pytest

from app.integrations.bailian import ModelUnavailable
from app.modules.outreach.outline_inputs import outline_dimensions, outline_inputs


def fixture_case():
    return SimpleNamespace(
        job_id="job",
        organization_id="org",
        candidate_id="candidate",
        snapshot={
            "screening_result": "passed",
            "artifact_refs": {
                f"D{i:02}": {"artifact_id": f"fixture-{i}", "version": 1} for i in range(1, 7)
            },
        },
        session_data={
            "upstream_content": {
                **{f"D{i:02}": {"fixture": True} for i in range(1, 6)},
                "D06": {"conclusion": "passed"},
            }
        },
    )


@pytest.mark.parametrize(
    "kind,code",
    [
        ("missing", "UPSTREAM_CONTENT_NOT_READY"),
        ("version", "UPSTREAM_VERSION_NOT_READY"),
        ("screening", "SCREENING_NOT_ELIGIBLE"),
        ("identity", "UPSTREAM_IDENTITY_MISMATCH"),
    ],
)
def test_preparation_rejects_invalid_upstream(kind, code):
    case = fixture_case()
    assert outline_inputs(case) == case.session_data["upstream_content"]
    if kind == "missing":
        del case.session_data["upstream_content"]["D05"]
    elif kind == "version":
        case.snapshot["artifact_refs"]["D03"]["version"] = True
    elif kind == "screening":
        case.session_data["upstream_content"]["D06"]["conclusion"] = "insufficient"
    else:
        case.session_data["upstream_content"]["D03"]["candidate_id"] = "other"
    with pytest.raises(ModelUnavailable, match=code):
        outline_inputs(case)


def test_dimensions_require_confirmation_and_preserve_custom_standard():
    case = fixture_case()
    with pytest.raises(ModelUnavailable, match="STANDARD_CONFIRMATION_REQUIRED"):
        outline_dimensions(case)
    dimension = {
        "id": "custom-research",
        "label": "研究能力",
        "indicators": "个人研究决策",
        "weight_percent": 100,
        "source_refs": ["fixture-D02"],
        "anchors": {key: "虚构锚点" for key in ["1-2", "3-4", "5-6", "7-8", "9-10"]},
    }
    case.session_data["job_interview_standard"] = {
        "standard": {
            "job_id": "job",
            "version": 2,
            "status": "confirmed",
            "confirmed_by": "reviewer",
            "dimensions": [dimension],
        }
    }
    actual = outline_dimensions(case)
    assert actual[0]["id"] == "custom-research"
    assert actual[0]["indicators"] == dimension["indicators"]
    assert float(actual[0]["weight_percent"]) == 100
    case.session_data["job_interview_standard"]["standard"]["status"] = "draft"
    with pytest.raises(ModelUnavailable, match="STANDARD_CONFIRMATION_REQUIRED"):
        outline_dimensions(case)
