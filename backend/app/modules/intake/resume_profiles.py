"""A04 extraction shared between independent talent intake and legacy job uploads."""

from app.core.artifacts import artifact_ref
from app.core.models import utcnow
from app.modules.intake import analysis
from app.modules.intake.form_sources import canonical_resume_facts, resume_objects
from app.modules.intake.schemas import Fact, ResumeProfile, ResumeResearchObject
from app.modules.intake.service import queue_step, save_profile


def prepare_profile(data, text, mode, *, full_form=True):
    profile = analysis.validate_quotes(
        ResumeProfile.model_validate(analysis.normalize_extraction_output(data)), text
    )
    if full_form:
        if profile.resume_form is None:
            raise ValueError("A04 output is missing its nine-module standard form")
        if mode == "live":
            profile.facts.update(
                {
                    key: Fact.model_validate(value)
                    for key, value in canonical_resume_facts(profile.resume_form).items()
                }
            )
            profile.research_objects = [
                ResumeResearchObject.model_validate(
                    {
                        **item,
                        "name": {k: v for k, v in item["name"].items() if k != "evidence_refs"},
                        "period": {k: v for k, v in item["period"].items() if k != "evidence_refs"},
                        "facts": {
                            key: {k: v for k, v in value.items() if k != "evidence_refs"}
                            for key, value in item["facts"].items()
                        },
                    }
                )
                for item in resume_objects(profile.resume_form)
            ]
        if "[[UNREADABLE_" in text:
            profile.resume_form.parse_status = "partial"
            profile.resume_form.limitations.append(
                "原文件包含尚未识别的页面或嵌入内容，需补充文字材料"
            )
    return profile


def save_application_profile(
    db, job, application, data, mode, *, full_form=True, start_research=True, pool_ref=None
):
    profile = prepare_profile(data, application.material_text, mode, full_form=full_form)
    artifact = save_profile(
        db,
        job,
        {
            **profile.model_dump(mode="json"),
            "unknown_fields": sorted(
                set(profile.unknown_fields)
                | {key for key, fact in profile.facts.items() if fact.status != "stated"}
            ),
        },
        "D03",
        source=mode,
        application=application,
        inherited=["manual"],
        inputs=[{"kind": "material", "id": application.file_id, "version": 1}],
    )
    if pool_ref:
        artifact.content = {**artifact.content, "talent_profile_ref": pool_ref}
    application.stage = "research" if start_research else "matched"
    name = profile.facts.get("name")
    if name and name.status == "stated" and isinstance(name.value, str) and len(name.value) <= 100:
        application.name = name.value
    application.revision += 1
    application.updated_at = utcnow()
    if start_research:
        queue_step(db, job, application, "research", input_refs=[artifact_ref(artifact)])
    return [artifact_ref(artifact)]
