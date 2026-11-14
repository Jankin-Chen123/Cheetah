import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.modules.outreach.minutes_worker import execute_minutes
from app.modules.outreach.models import ModelStep, OutreachArtifact, OutreachCase
from app.modules.outreach.postprocessing import schedule_postprocessing
from app.modules.outreach.report_worker import execute_report_step


@pytest.mark.parametrize("score,report_count", [(4, 1), (1, 0), (None, 0)])
def test_end_to_postprocessing_survives_poll_restart_without_approval(
    tmp_path, monkeypatch, score, report_count
):
    engine = create_engine(f"sqlite:///{tmp_path / 'postprocessing.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        session.add(
            OutreachCase(
                id="case",
                organization_id="org",
                owner_id="reviewer",
                candidate_id="candidate",
                application_id="application",
                job_id="job",
                status="ended",
                stop_status="confirmed",
                snapshot={"fixture_only": True},
                session_data={
                    "answers": [
                        {
                            "id": "a1",
                            "text": "我负责测试，完成三个项目",
                            "question": {},
                        }
                    ]
                },
            )
        )

    def model(settings, instruction, context):
        if "facts" in context["schema"]["properties"]:
            content = {
                "facts": [
                    {
                        "statement": "候选人自述负责测试",
                        "answer_id": "a1",
                        "quote": "我负责测试",
                        "kind": "responsibility",
                    }
                ],
                "gaps": ["结果尚未独立核实"],
                "conflicts": [],
            }
        elif "assessments" in context["schema"]["properties"]:
            content = {
                "assessments": [
                    {
                        "dimension_id": dimension,
                        "score": score,
                        "evidence_ids": ["a1"] if score is not None else [],
                        "reason": "隔离流程测试",
                    }
                    for dimension in ["responsibility", "results"]
                ]
            }
        else:
            content = {"match_highlights": [{"text": "候选人自述负责测试", "answer_ids": ["a1"]}]}
        return {"content": content, "model": "isolated-test-double", "usage": None}

    monkeypatch.setattr("app.modules.outreach.minutes_worker.generate_json", model)
    monkeypatch.setattr("app.modules.outreach.report_worker.generate_json", model)
    with Session(engine) as session, session.begin():
        assert schedule_postprocessing(session, case_id="unrelated-case") == 0
        assert session.scalar(select(func.count()).select_from(ModelStep)) == 0
    for step in ["D08", "D09", "D10"]:
        with Session(engine) as session, session.begin():
            count = schedule_postprocessing(session)
            assert count == (0 if step == "D10" and not report_count else 1)
        # A new process/session polls the same committed receipts.
        with Session(engine) as session, session.begin():
            assert schedule_postprocessing(session) == 0
            task = session.scalar(select(ModelStep).where(ModelStep.step == step))
            task_id = task.id if task else None
        if task_id:
            executor = execute_minutes if step == "D08" else execute_report_step
            executor(engine, Settings(), task_id)
            executor(engine, Settings(), task_id)
    with Session(engine) as session, session.begin():
        assert schedule_postprocessing(session) == 0
        assert (
            session.scalar(select(func.count()).select_from(OutreachArtifact)) == 2 + report_count
        )
        report = session.scalar(select(OutreachArtifact).where(OutreachArtifact.type == "D10"))
        if report:
            assert report.review_status == "pending_review"
            assert "结果尚未独立核实" in report.content["unknowns"]
        case = session.get(OutreachCase, "case")
        case.session_data = {**case.session_data, "correction_requires_recompute": True}
        for artifact in session.scalars(select(OutreachArtifact)):
            artifact.valid = False
        case.revision += 1
        assert schedule_postprocessing(session) == 0
