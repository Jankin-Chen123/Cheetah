"""Model-assisted internal assessment; program gates recommendation drafts."""

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.integrations.bailian import generate_json
from app.modules.outreach.artifacts import invalidate_downstream, save_artifact
from app.modules.outreach.evaluation import (
    EvaluationTemplate,
    EvidenceAssessment,
    validate_evaluation,
)
from app.modules.outreach.models import OutreachArtifact, OutreachCase
from app.modules.outreach.templates import ReportTemplate, bind_templates


class AssessmentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assessments: list[EvidenceAssessment]


class RecommendationClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000)
    answer_ids: list[str] = Field(min_length=1, max_length=12)


class RecommendationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    match_highlights: list[RecommendationClaim] = Field(min_length=1, max_length=10)
    unknowns: list[str] = Field(default_factory=list, max_length=20)


def generate_evaluation(
    session: Session, case: OutreachCase, settings: Settings, *, model_result=None
):
    minutes = session.scalar(
        select(OutreachArtifact).where(
            OutreachArtifact.case_id == case.id,
            OutreachArtifact.type == "D08",
            OutreachArtifact.valid.is_(True),
        )
    )
    if minutes is None:
        raise ValueError("CURRENT_MINUTES_REQUIRED")
    bound = bind_templates(case, settings, "D09")
    template = EvaluationTemplate.model_validate(bound["content"])
    answers = {a["id"]: a["text"] for a in minutes.content["qa"]}
    result = (
        model_result
        if model_result is not None
        else generate_json(
            settings,
            "Assess only actual answers against the supplied DEMO rubric. "
            "Missing evidence means null score. Return assessments JSON.",
            {
                "schema": AssessmentOutput.model_json_schema(),
                "template": template.model_dump(),
                "minutes": minutes.content,
            },
        )
    )
    output = AssessmentOutput.model_validate(result["content"])
    content = validate_evaluation(
        template, output.assessments, answers, fixture_only=case.snapshot["fixture_only"]
    )
    provenance = {
        "source_mode": "live",
        "inherited_source_modes": ["mock", "manual"],
        "fixture_only": True,
        "knowledge_preview": case.session_data.get("knowledge_preview", False),
        "demo_rules": template.status == "demo",
        "model": result["model"],
        "usage": result["usage"],
        "template": template.model_dump(),
        "template_sha256": bound["sha256"],
    }
    invalidate_downstream(session, case, "D09")
    evaluation = save_artifact(
        session,
        case,
        "D09",
        content,
        provenance,
        [{"kind": "artifact", "id": minutes.id, "version": minutes.version}],
    )
    case.revision += 1
    return evaluation


def generate_recommendation(
    session: Session, case: OutreachCase, settings: Settings, *, model_result=None
):
    evaluation = session.scalar(
        select(OutreachArtifact).where(
            OutreachArtifact.case_id == case.id,
            OutreachArtifact.type == "D09",
            OutreachArtifact.valid.is_(True),
        )
    )
    if evaluation is None or evaluation.content["conclusion"] != "recommended":
        raise ValueError("RECOMMENDATION_NOT_ELIGIBLE")
    bound = bind_templates(case, settings, "D10")
    template = ReportTemplate.model_validate(bound["content"])
    expected = evaluation.provenance.get("template", {}).get("report_template_version", 1)
    if template.version != expected:
        raise ValueError("REPORT_TEMPLATE_VERSION_MISMATCH")
    answers = case.session_data.get("answers", [])
    result = (
        model_result
        if model_result is not None
        else generate_json(
            settings,
            "Write Chinese HR recommendation highlights from actual answers only. "
            "Cite answer_ids. Exclude internal scores and contact details.",
            {
                "schema": RecommendationOutput.model_json_schema(),
                "answers": answers,
                "evaluation": evaluation.content,
                "report_template": template.model_dump(),
            },
        )
    )
    output = RecommendationOutput.model_validate(result["content"])
    allowed = {answer["id"] for answer in answers}
    for claim in output.match_highlights:
        if not set(claim.answer_ids).issubset(allowed):
            raise ValueError("UNKNOWN_REPORT_EVIDENCE")
    markdown = (
        f"# {template.title}\n\n> {template.disclaimer}\n\n## {template.highlights_heading}\n\n"
        + "\n\n".join(claim.text for claim in output.match_highlights)
    )
    markdown += f"\n\n## {template.unknowns_heading}\n\n" + "\n".join(output.unknowns)
    if case.session_data.get("knowledge_preview", False):
        markdown += (
            "\n\n> 本报告使用未审核方法知识的开发预览，评估规则为演示配置，不具有正式专业评估效力。"
        )
    report = save_artifact(
        session,
        case,
        "D10",
        {**output.model_dump(), "content_markdown": markdown},
        {
            "source_mode": "live",
            "inherited_source_modes": ["mock", "manual"],
            "fixture_only": True,
            "knowledge_preview": case.session_data.get("knowledge_preview", False),
            "demo_rules": evaluation.content.get("demo_rules", False),
            "model": result["model"],
            "usage": result["usage"],
            "report_template_version": template.version,
            "report_template": template.model_dump(),
            "template_sha256": bound["sha256"],
        },
        [{"kind": "artifact", "id": evaluation.id, "version": evaluation.version}],
    )
    case.revision += 1
    return report
