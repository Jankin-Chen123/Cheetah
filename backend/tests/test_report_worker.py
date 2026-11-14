import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.modules.outreach.models import ModelStep, OutreachArtifact, OutreachCase
from app.modules.outreach.report_worker import execute_report_step
from app.modules.outreach.steps import register_step


@pytest.mark.parametrize(
    "score,conclusion", [(4, "recommended"), (1, "rejected"), (None, "insufficient")]
)
def test_report_worker_three_decisions(tmp_path, monkeypatch, score, conclusion):
    engine = create_engine(f"sqlite:///{tmp_path / 'reports.db'}")
    Base.metadata.create_all(engine)
    answers = [{"id": "a1", "text": "虚构职责及结果回答", "question": {}}]
    with Session(engine) as session, session.begin():
        session.add(
            OutreachCase(
                id="case",
                organization_id="org",
                owner_id="owner",
                application_id="app",
                candidate_id="candidate",
                job_id="job",
                snapshot={"fixture_only": True},
                session_data={"answers": answers, "knowledge_preview": True},
            )
        )
        session.add(
            OutreachArtifact(
                id="minutes",
                case_id="case",
                type="D08",
                version=1,
                content={"qa": answers},
                provenance={},
                input_refs=[],
            )
        )
        session.flush()
        task, _ = register_step(session, "case", "D09", 1)
        evaluation_task = task.id
    calls = []

    def model(settings, instruction, context):
        calls.append(instruction)
        if "assessments" in context["schema"]["properties"]:
            content = {
                "assessments": [
                    {
                        "dimension_id": dimension,
                        "score": score,
                        "evidence_ids": ["a1"] if score is not None else [],
                        "reason": "隔离流程验证",
                    }
                    for dimension in ["responsibility", "results"]
                ]
            }
        else:
            content = {
                "match_highlights": [{"text": "虚构推荐亮点", "answer_ids": ["a1"]}],
                "unknowns": ["演示规则，不具专业评估效力"],
            }
        return {"content": content, "model": "isolated-test-double", "usage": None}

    monkeypatch.setattr("app.modules.outreach.report_worker.generate_json", model)
    execute_report_step(engine, Settings(), evaluation_task)
    with Session(engine) as session, session.begin():
        evaluation = session.scalar(select(OutreachArtifact).where(OutreachArtifact.type == "D09"))
        assert evaluation.content["conclusion"] == conclusion
        case = session.get(OutreachCase, "case")
        task, _ = register_step(session, "case", "D10", case.revision)
        report_task = task.id
    execute_report_step(engine, Settings(), report_task)
    with Session(engine) as session:
        report = session.scalar(select(OutreachArtifact).where(OutreachArtifact.type == "D10"))
        if score == 4:
            assert report and report.review_status == "pending_review"
            assert session.get(ModelStep, report_task).status == "completed"
            assert "mock" in report.provenance["inherited_source_modes"]
            assert report.provenance["knowledge_preview"] is True
            assert report.provenance["demo_rules"] is True
            assert "未审核方法知识" in report.content["content_markdown"]
        else:
            assert report is None
            assert session.get(ModelStep, report_task).status == "failed"
        assert len(calls) == (2 if score == 4 else 1)
