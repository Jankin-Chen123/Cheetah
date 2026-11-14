from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import IntakeJob
from app.modules.intake.material_job import apply_material_job_labels
from app.modules.intake.schemas import CreateJobInput
from tests.conftest import post


def test_material_only_input_and_pending_labels_not_source_facts(api, runtime):
    job = post(api, "/jobs", {"material_text": "虚构沟通记录，岗位待确认"})
    assert job["title"] == "待识别岗位"
    with Session(runtime[1]) as db:
        saved = db.scalar(select(IntakeJob).where(IntakeJob.id == job["id"]))
        assert saved.company == "待识别企业"
        assert saved.material_fields["title"] is None
        assert saved.material_fields["company"] is None


def test_explicit_empty_labels_rejected():
    assert CreateJobInput(material_text="虚构材料").title is None
    with pytest.raises(ValidationError):
        CreateJobInput(title=" ", material_text="虚构材料")


def test_labels_only_promoted_from_stated_form_without_overwriting_manual_input():
    def fact(value, status="stated"):
        return SimpleNamespace(value=value, status=status)

    job = SimpleNamespace(
        material_fields={"company": "人工企业"},
        title="待识别岗位",
        company="人工企业",
        location=None,
        salary=None,
    )
    profile = SimpleNamespace(
        job_form=SimpleNamespace(
            fields={
                "岗位名称": fact("虚构工程师"),
                "客户企业名称": fact("模型企业"),
                "工作地点": fact(None, "conflict"),
                "转正薪资": fact("X" * 101),
            }
        )
    )
    apply_material_job_labels(job, profile)
    assert job.title == "虚构工程师"
    assert job.company == "人工企业"
    assert job.location is None
    assert job.salary is None
