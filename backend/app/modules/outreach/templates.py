"""Validated, immutable per-case configuration snapshots; no executable templates."""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.outreach.evaluation import EvaluationTemplate

CONFIG_DIRECTORY = Path(__file__).resolve().parents[3] / "config"


class ReportTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    version: int = Field(ge=1)
    status: Literal["demo", "approved"]
    title: str = Field(min_length=1, max_length=200)
    highlights_heading: str = Field(min_length=1, max_length=200)
    unknowns_heading: str = Field(min_length=1, max_length=200)
    disclaimer: str = Field(min_length=1, max_length=2000)


def snapshot(model):
    content = model.model_dump()
    digest = hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return {"content": content, "sha256": digest}


def bind_templates(case, settings, step):
    data = dict(case.session_data)
    key = "evaluation_template" if step == "D09" else "report_template"
    model_type = EvaluationTemplate if step == "D09" else ReportTemplate
    if key in data:
        bound = data[key]
        model = model_type.model_validate(bound["content"])
        if snapshot(model) != bound:
            raise ValueError("TEMPLATE_SNAPSHOT_HASH_MISMATCH")
        return bound
    path = (
        settings.evaluation_template_path or CONFIG_DIRECTORY / "demo-evaluation.v1.json"
        if step == "D09"
        else settings.report_template_path or CONFIG_DIRECTORY / "demo-report.v1.json"
    )
    model = model_type.model_validate_json(path.read_text(encoding="utf8"))
    if model.status == "demo" and not case.snapshot.get("fixture_only"):
        raise ValueError("DEMO_TEMPLATE_REQUIRES_FIXTURE")
    bound = snapshot(model)
    case.session_data = {**data, key: bound}
    return bound
