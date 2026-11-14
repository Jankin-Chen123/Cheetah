from types import SimpleNamespace

import pytest

from app.modules.outreach.career_confirmation import (
    confirm_field,
    confirmed_upstream,
    revoke_confirmation,
    unresolved_career_conflicts,
)
from app.modules.outreach.report_profile import professional_profile


def test_confirmation_and_revocation_persist_and_expire_report(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.core.database import Base
    from app.modules.outreach.models import OutreachArtifact, OutreachCase

    engine = create_engine(f"sqlite:///{tmp_path / 'career.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db, db.begin():
        case = OutreachCase(
            id="c",
            organization_id="org",
            owner_id="owner",
            application_id="app",
            candidate_id="candidate",
            job_id="job",
            snapshot={"artifact_refs": {"D03": {"version": 1}}},
            session_data={
                "answers": [{"id": "a", "text": "期望月薪税前2万元", "version": 1}],
                "upstream_content": {"D03": {}},
            },
        )
        db.add(case)
        db.flush()
        db.add_all(
            [
                OutreachArtifact(
                    id="m",
                    case_id="c",
                    type="D08",
                    version=1,
                    content={"conflicts": []},
                    provenance={},
                    input_refs=[],
                ),
                OutreachArtifact(
                    id="r",
                    case_id="c",
                    type="D10",
                    version=1,
                    content={},
                    provenance={},
                    input_refs=[],
                    review_status="approved",
                ),
            ]
        )
    with Session(engine) as db, db.begin():
        case = db.get(OutreachCase, "c")
        receipt = confirm_field(
            db,
            case,
            expected_revision=case.revision,
            minutes_id="m",
            minutes_version=1,
            field_path="job_preferences.salary_expectation",
            value="月薪税前2万元",
            answer_id="a",
            quote="期望月薪税前2万元",
            reason="保留月薪税前口径",
            actor_id="owner",
        )
        receipt_id = receipt["id"]
    with Session(engine) as db, db.begin():
        case = db.get(OutreachCase, "c")
        report = db.get(OutreachArtifact, "r")
        assert not report.valid and report.review_status == "expired"
        assert (
            confirmed_upstream(case, db.get(OutreachArtifact, "m"))[0]["D03"]["job_preferences"][
                "salary_expectation"
            ]
            == "月薪税前2万元"
        )
        revoke_confirmation(db, case, receipt_id, case.revision, "候选人要求待确认", "owner")
    with Session(engine) as db:
        case = db.get(OutreachCase, "c")
        upstream, receipts = confirmed_upstream(case, db.get(OutreachArtifact, "m"))
        assert receipts == [] and upstream["D03"] == {}
        assert len(case.session_data["career_confirmations"]) == 1
        assert (
            case.session_data["career_confirmation_revocations"][0]["reason"] == "候选人要求待确认"
        )


def test_confirmation_is_version_bound_and_preserves_original(monkeypatch):
    invalidated = []
    monkeypatch.setattr(
        "app.modules.outreach.career_confirmation.invalidate_downstream",
        lambda session, case, kind: invalidated.append(kind),
    )
    case = SimpleNamespace(
        id="case",
        revision=1,
        snapshot={"artifact_refs": {"D03": {"version": 1}}},
        session_data={
            "answers": [{"id": "a1", "text": "现在常住虚构城市乙", "version": 1}],
            "upstream_content": {"D03": {"profile": {"current_city": "虚构城市甲"}}},
        },
    )
    minutes = SimpleNamespace(
        id="m1",
        case_id="case",
        type="D08",
        valid=True,
        version=1,
        content={
            "conflicts": ["履历与口述城市不同", "业绩冲突"],
            "qa": case.session_data["answers"].copy(),
            "career_conflict_evidence": [
                {
                    "conflict_index": 0,
                    "field_path": "profile.current_city",
                    "resume_value": "虚构城市甲",
                    "spoken_value": "虚构城市乙",
                    "answer_id": "a1",
                    "answer_quote": "现在常住虚构城市乙",
                }
            ],
        },
    )
    session = SimpleNamespace(get=lambda *args: minutes)
    fields = dict(
        expected_revision=1,
        minutes_id="m1",
        minutes_version=1,
        field_path="profile.current_city",
        value="虚构城市乙",
        answer_id="a1",
        quote="现在常住虚构城市乙",
        reason="已核对本次明确口述",
        actor_id="reviewer",
        conflict_index=0,
    )
    with pytest.raises(ValueError, match="CAREER_SOURCE_QUOTE_INVALID"):
        confirm_field(session, case, **{**fields, "value": "不存在的值"})
    with pytest.raises(ValueError, match="CAREER_CONFLICT_EVIDENCE_MISMATCH"):
        confirm_field(session, case, **{**fields, "field_path": "profile.current_role"})
    confirm_field(session, case, **fields)
    assert invalidated == ["D09"] and case.revision == 2
    upstream, receipts = confirmed_upstream(case, minutes)
    assert upstream["D03"]["profile"]["current_city"] == "虚构城市乙"
    assert case.session_data["upstream_content"]["D03"]["profile"]["current_city"] == "虚构城市甲"
    assert receipts[0]["conflict_text"] == "履历与口述城市不同"
    assert unresolved_career_conflicts(case, minutes, receipts) == ["业绩冲突"]
    with pytest.raises(ValueError, match="VERSION_CONFLICT"):
        confirm_field(session, case, **fields)
    case.session_data["answers"][0]["version"] = 2
    assert confirmed_upstream(case, minutes)[1] == []
    case.session_data["answers"][0]["version"] = 1
    revoke_confirmation(session, case, receipts[0]["id"], case.revision, "撤销", "reviewer")
    assert unresolved_career_conflicts(case, minutes, confirmed_upstream(case, minutes)[1]) == [
        "履历与口述城市不同",
        "业绩冲突",
    ]
    minutes.version = 2
    assert confirmed_upstream(case, minutes)[1] == []


def test_dynamic_slots_survive_revocation_without_reindexing(monkeypatch):
    monkeypatch.setattr(
        "app.modules.outreach.career_confirmation.invalidate_downstream", lambda *args: None
    )
    case = SimpleNamespace(
        id="case",
        revision=1,
        snapshot={"artifact_refs": {"D03": {"version": 1}}},
        session_data={
            "answers": [
                {"id": "a", "text": "甲公司"},
                {"id": "b", "text": "乙公司 新乙公司 负责交接 负责验收"},
            ],
            "upstream_content": {"D03": {"employment": []}},
        },
    )
    minutes = SimpleNamespace(
        id="m", case_id="case", valid=True, type="D08", version=1, content={"conflicts": []}
    )
    session = SimpleNamespace(get=lambda *args: minutes)

    def confirm(path, value, answer_id="b"):
        return confirm_field(
            session,
            case,
            expected_revision=case.revision,
            minutes_id="m",
            minutes_version=1,
            field_path=path,
            value=value,
            answer_id=answer_id,
            quote=value,
            reason="核对候选人原话",
            actor_id="owner",
        )

    first = confirm("employment.0.company", "甲公司", "a")
    with pytest.raises(ValueError, match="CAREER_FIELD_INVALID"):
        confirm("employment.2.company", "乙公司")
    confirm("employment.1.company", "乙公司")
    replacement = confirm("employment.1.company", "新乙公司")
    first_duty = confirm("employment.1.responsibilities.0", "负责交接")
    second_duty = confirm("employment.1.responsibilities.1", "负责验收")
    for receipt in (first, first_duty):
        revoke_confirmation(session, case, receipt["id"], case.revision, "撤销", "owner")

    upstream, active = confirmed_upstream(case, minutes)
    assert upstream["D03"]["employment"] == [
        {},
        {"company": "新乙公司", "responsibilities": ["", "负责验收"]},
    ]
    assert [receipt["id"] for receipt in active] == [replacement["id"], second_duty["id"]]
    profile, _ = professional_profile(upstream)
    assert [row["company"] for row in profile["work_history"]] == ["新乙公司"]
    assert profile["work_history"][0]["responsibilities"] == ["负责验收"]
    revoke_confirmation(session, case, replacement["id"], case.revision, "撤销", "owner")
    assert "company" not in confirmed_upstream(case, minutes)[0]["D03"]["employment"][1]
    case.session_data["answers"][1]["version"] = 2
    assert confirmed_upstream(case, minutes) == ({"D03": {"employment": []}}, [])
