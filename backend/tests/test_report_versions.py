import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.modules.outreach.artifacts import (
    export_markdown,
    invalidate_downstream,
    review_report,
    save_artifact,
)
from app.modules.outreach.models import OutreachCase


def test_approval_version_and_correction_gates():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        case = OutreachCase(
            id="fixture",
            organization_id="org",
            owner_id="owner",
            application_id="app",
            candidate_id="candidate",
            job_id="job",
            snapshot={},
            session_data={},
        )
        session.add(case)
        session.flush()
        with pytest.raises(ValueError, match="not eligible"):
            save_artifact(session, case, "D10", {}, {}, [])
        evaluation = save_artifact(session, case, "D09", {"conclusion": "recommended"}, {}, [])
        report = save_artifact(
            session,
            case,
            "D10",
            {"content_markdown": "虚构演示草案"},
            {"inherited_source_modes": ["mock"]},
            [{"id": evaluation.id}],
        )
        with pytest.raises(ValueError, match="not approved"):
            export_markdown(report)
        review_report(report, 1, 1, "approve", "owner", "虚构流程验收")
        assert export_markdown(report) == "虚构演示草案"
        with pytest.raises(ValueError, match="Version conflict"):
            review_report(report, 1, 1, "approve", "owner", "重复旧版本")
        invalidate_downstream(session, case, "D08")
        with pytest.raises(ValueError, match="expired"):
            export_markdown(report)
        assert report.provenance["inherited_source_modes"] == ["mock"]


def test_unresolved_career_conflict_blocks_approval_and_old_approval_export():
    from types import SimpleNamespace

    report = SimpleNamespace(
        type="D10",
        valid=True,
        version=1,
        revision=1,
        review_status="pending_review",
        provenance={},
        content={
            "client_profile": {"unresolved_conflicts": ["任期冲突"]},
            "content_markdown": "虚构草稿",
        },
    )
    with pytest.raises(ValueError, match="REPORT_FACT_CONFLICT_REQUIRES_CORRECTION"):
        review_report(report, 1, 1, "approve", "reviewer", "已核读")
    assert report.review_status == "pending_review"
    report.review_status = "approved"
    with pytest.raises(ValueError, match="REPORT_FACT_CONFLICT_REQUIRES_CORRECTION"):
        export_markdown(report)
    review_report(report, 1, 1, "reject", "reviewer", "需更正事实后重算")
    assert report.review_status == "rejected"
