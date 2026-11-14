import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.modules.outreach.models import ModelStep, OutreachArtifact, OutreachCase
from app.modules.outreach.steps import register_step
from app.modules.outreach.worker import execute_outline


@pytest.mark.parametrize("change_during_model", [None, "stop", "upstream"])
@pytest.mark.parametrize("has_methods", [False, True])
def test_outline_worker_releases_transaction_and_rechecks_stop(
    tmp_path, monkeypatch, change_during_model, has_methods
):
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        session.add(
            OutreachCase(
                id="case",
                organization_id="org",
                owner_id="owner",
                application_id="app",
                candidate_id="candidate",
                job_id="job",
                snapshot={
                    "fixture_only": True,
                    "screening_result": "passed",
                    "artifact_refs": {
                        f"D{i:02}": {"artifact_id": f"fixture-{i}", "version": 1}
                        for i in range(1, 7)
                    },
                },
                session_data={
                    "upstream_content": json.loads(
                        (Path(__file__).parents[1] / "config/fixture-upstream.v1.json").read_text(
                            encoding="utf8"
                        )
                    )
                },
            )
        )
        session.flush()
        task, _ = register_step(session, "case", "D07", 1)
        task_id = task.id
    monkeypatch.setattr(
        "app.modules.outreach.worker.retrieve",
        lambda *a, **k: [{"entry_id": "m1"}] if has_methods else [],
    )

    def model(settings, instruction, context):
        with Session(engine) as session, session.begin():
            assert session.get(ModelStep, task_id).status == "running"
            case = session.get(OutreachCase, "case")
            if change_during_model == "stop":
                case.stop_status = "requested"
                case.revision += 1
            elif change_during_model == "upstream":
                case.snapshot = {
                    **case.snapshot,
                    "artifact_refs": {
                        **case.snapshot["artifact_refs"],
                        "D04": {"artifact_id": "fixture-4", "version": 2},
                    },
                }
        return {
            "model": "isolated-test-double",
            "usage": None,
            "content": {
                "questions": [
                    {
                        "id": "q1",
                        "dimension_id": "responsibility",
                        "question": "虚构问题？",
                        "method_entry_ids": ["m1"] if has_methods else [],
                        "evidence_target": "个人职责",
                    },
                    {
                        "id": "q2",
                        "dimension_id": "results",
                        "question": "成果如何测量？",
                        "evidence_target": "成果口径",
                    },
                ]
            },
        }

    monkeypatch.setattr("app.modules.outreach.worker.generate_json", model)
    execute_outline(engine, Settings(), task_id)
    with Session(engine) as session:
        task = session.get(ModelStep, task_id)
        assert (
            task.status
            == {None: "completed", "stop": "cancelled", "upstream": "failed"}[change_during_model]
        )
        if change_during_model == "upstream":
            assert task.detail["error_code"] == "OUTLINE_INPUT_CHANGED_DURING_INFERENCE"
        assert session.scalar(select(func.count()).select_from(OutreachArtifact)) == (
            0 if change_during_model else 1
        )
    if change_during_model:
        return
    with Session(engine) as session, session.begin():
        case = session.get(OutreachCase, "case")
        next_task, _ = register_step(session, case.id, "D07", case.revision)
        next_id = next_task.id

    def unexpected(*args):
        raise AssertionError("Current preparation must be reused without inference")

    monkeypatch.setattr("app.modules.outreach.worker.generate_json", unexpected)
    execute_outline(engine, Settings(), next_id)
    with Session(engine) as session:
        first = session.get(ModelStep, task_id)
        second = session.get(ModelStep, next_id)
        assert second.status == "completed"
        assert second.detail["result_ref"] == first.detail["result_ref"]
        assert session.scalar(select(func.count()).select_from(OutreachArtifact)) == 1
