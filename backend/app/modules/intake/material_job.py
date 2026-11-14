"""Promote validated A01 facts to job labels without treating pending labels as facts."""

from app.modules.intake.schemas import JobAnalysis


def apply_material_job_labels(job, profile: JobAnalysis) -> None:
    if profile.job_form is None:
        return
    names = {
        "title": "岗位名称",
        "company": "客户企业名称",
        "location": "工作地点",
        "salary": "转正薪资",
    }
    for attribute, field in names.items():
        if job.material_fields.get(attribute) is not None:
            continue
        fact = profile.job_form.fields.get(field)
        if fact and fact.status == "stated" and fact.value and len(fact.value) <= 100:
            setattr(job, attribute, fact.value)
