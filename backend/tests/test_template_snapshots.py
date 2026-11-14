import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.outreach.evaluation import EvaluationTemplate
from app.modules.outreach.models import OutreachCase
from app.modules.outreach.templates import bind_templates


def test_bound_report_survives_config_change_and_rejects_tampering(tmp_path):
    payload = json.loads(
        (Path(__file__).parents[1] / "config/demo-report.v1.json").read_text(encoding="utf8")
    )
    path = tmp_path / "report.json"
    path.write_text(json.dumps(payload), encoding="utf8")
    settings = Settings(report_template_path=path)
    case = OutreachCase(snapshot={"fixture_only": True}, session_data={})
    first = bind_templates(case, settings, "D10")
    path.write_text(json.dumps({**payload, "version": 2, "title": "Changed"}), encoding="utf8")
    assert bind_templates(case, settings, "D10") == first
    other = OutreachCase(snapshot={"fixture_only": True}, session_data={})
    assert bind_templates(other, settings, "D10")["content"]["version"] == 2
    case.session_data["report_template"]["content"]["title"] = "Tampered"
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        bind_templates(case, settings, "D10")
    with pytest.raises(ValueError, match="REQUIRES_FIXTURE"):
        bind_templates(OutreachCase(snapshot={}, session_data={}), settings, "D10")


def test_professional_configuration_requires_complete_score_anchors():
    payload = json.loads(
        (Path(__file__).parents[1] / "config/demo-evaluation.v1.json").read_text(encoding="utf8")
    )
    payload["status"] = "approved"
    with pytest.raises(ValidationError, match="requires scoring anchors"):
        EvaluationTemplate.model_validate(payload)
    for dimension in payload["dimensions"]:
        dimension["scoring_anchors"] = {str(i): f"Fictional anchor {i}" for i in range(6)}
    assert EvaluationTemplate.model_validate(payload).status == "approved"
    payload["dimensions"][0]["scoring_anchors"].pop("0")
    with pytest.raises(ValidationError, match="zero to five"):
        EvaluationTemplate.model_validate(payload)
