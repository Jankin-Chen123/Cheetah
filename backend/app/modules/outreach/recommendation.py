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
from app.modules.outreach.postprocessing_prompts import (
    EVALUATION_INSTRUCTION,
    PROMPT_VERSION,
    RECOMMENDATION_INSTRUCTION,
)
from app.modules.outreach.provenance import inherited_provenance
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


def validate_indicator_scoring(assessments, indicator_evidence):
    insufficient = {
        row["dimension_id"]
        for row in indicator_evidence
        if row.get("evidence_sufficiency") == "INSUFFICIENT"
    }
    if any(item.score is not None and item.dimension_id in insufficient for item in assessments):
        raise ValueError("INSUFFICIENT_INDICATOR_REQUIRES_REVIEW")


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
            EVALUATION_INSTRUCTION,
            {
                "schema": AssessmentOutput.model_json_schema(),
                "template": template.model_dump(),
                "minutes": minutes.content,
            },
        )
    )
    output = AssessmentOutput.model_validate(result["content"])
    validate_indicator_scoring(output.assessments, minutes.content.get("indicator_evidence", []))
    content = validate_evaluation(
        template,
        output.assessments,
        answers,
        fixture_only=case.snapshot["fixture_only"],
        evidence_items=minutes.content.get("evidence_items", []),
    )
    content["gaps"] = list(minutes.content.get("gaps", []))
    content["conflicts"] = list(minutes.content.get("conflicts", []))
    content["extraction_limitations"] = list(minutes.content.get("extraction_limitations", []))
    content["indicator_evidence"] = list(minutes.content.get("indicator_evidence", []))
    content["evidence_items"] = list(minutes.content.get("evidence_items", []))
    content["dimension_coverage"] = list(minutes.content.get("dimension_coverage", []))
    provenance = {
        "source_mode": "live",
        "prompt_version": PROMPT_VERSION,
        **inherited_provenance(case, minutes),
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
            RECOMMENDATION_INSTRUCTION,
            {
                "schema": RecommendationOutput.model_json_schema(),
                "answers": answers,
                "evaluation": evaluation.content,
                "report_template": template.model_dump(),
            },
        )
    )
    output = RecommendationOutput.model_validate(result["content"])
    allowed = {answer["id"] for answer in answers if answer["text"].strip()}
    for claim in output.match_highlights:
        if not claim.text.strip() or not set(claim.answer_ids).issubset(allowed):
            raise ValueError("UNKNOWN_REPORT_EVIDENCE")
    if model_result is None and not evaluation.content.get("demo_rules", False):
        from app.modules.outreach.budget import reserve_model_request
        from app.modules.outreach.report_review import review_report_claims

        reserve_model_request(case, settings, "D10_evidence_review")
        result["quality_review"] = review_report_claims(
            settings, [claim.model_dump() for claim in output.match_highlights], answers
        )
    # A model cannot silently omit unresolved upstream qualifications.
    output.unknowns = list(
        dict.fromkeys(
            [
                *output.unknowns,
                *evaluation.content.get("gaps", []),
                *evaluation.content.get("conflicts", []),
            ]
        )
    )
    markdown = (
        f"# {template.title}\n\n> {template.disclaimer}\n\n"
        f"## 第一部分｜猎头机构评估\n\n## {template.highlights_heading}\n\n"
        + "\n\n".join(claim.text for claim in output.match_highlights)
    )
    markdown += f"\n\n## {template.unknowns_heading}\n\n" + "\n".join(output.unknowns)
    from app.modules.outreach.report_profile import professional_profile

    client_profile, career_section = professional_profile(
        case.session_data.get("upstream_content", {})
    )
    markdown = markdown.replace(
        "## 第一部分｜猎头机构评估",
        "## 第一部分｜猎头机构评估\n\n"
        f"推荐职位：{client_profile['recommended_job_title']}\n\n"
        f"候选人：{client_profile['candidate_display_name']}",
        1,
    )
    markdown += "\n\n" + career_section
    inherited = inherited_provenance(case, evaluation)
    if inherited["fixture_only"] or "mock" in inherited["inherited_source_modes"]:
        markdown += "\n\n> 本报告包含虚构或模拟来源，仅用于受限流程验证。"
    if "unknown" in inherited["inherited_source_modes"]:
        markdown += "\n\n> 部分输入来源未确认，交付前须核实。"
    if case.session_data.get("knowledge_preview", False):
        markdown += (
            "\n\n> 本报告使用未审核方法知识的开发预览，评估规则为演示配置，不具有正式专业评估效力。"
        )
    report = save_artifact(
        session,
        case,
        "D10",
        {**output.model_dump(), "content_markdown": markdown, "client_profile": client_profile},
        {
            "source_mode": "live",
            "prompt_version": PROMPT_VERSION,
            **inherited,
            "knowledge_preview": case.session_data.get("knowledge_preview", False),
            "demo_rules": evaluation.content.get("demo_rules", False),
            "model": result["model"],
            "usage": result["usage"],
            "report_template_version": template.version,
            "client_context": case.session_data.get("client_context"),
            "quality_review": result.get("quality_review"),
            "report_template": template.model_dump(),
            "template_sha256": bound["sha256"],
        },
        [{"kind": "artifact", "id": evaluation.id, "version": evaluation.version}],
    )
    case.revision += 1
    return report
