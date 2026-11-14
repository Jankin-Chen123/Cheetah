import pytest

from app.modules.outreach.minutes import (
    MinuteFact,
    Minutes,
    validate_indicator_evidence,
    validate_minutes,
)


@pytest.mark.parametrize("mode", ["missing", "duplicate", "invented", "empty_sufficient"])
def test_indicator_matrix_cannot_invent_coverage_or_evidence(mode):
    row = {
        "dimension_id": "research",
        "indicator_ref": "dimensions[0].indicators",
        "answer_ids": [],
        "evidence_sufficiency": "INSUFFICIENT",
        "sufficiency_reason": "尚未取得回答",
        "gaps": ["个人行动未知"],
    }
    definitions = [{"dimension_id": "research", "indicator_ref": row["indicator_ref"]}]
    minutes = Minutes(facts=[], indicator_evidence=[row])
    validate_indicator_evidence(minutes, definitions, [])
    if mode == "missing":
        minutes.indicator_evidence = []
    elif mode == "duplicate":
        minutes.indicator_evidence *= 2
    elif mode == "invented":
        minutes.indicator_evidence[0].answer_ids = ["invented"]
    else:
        minutes.indicator_evidence[0].evidence_sufficiency = "SUFFICIENT"
    with pytest.raises(ValueError, match="INDICATOR_"):
        validate_indicator_evidence(minutes, definitions, [])


def test_minutes_require_actual_answer_and_exact_quote():
    fact = MinuteFact(
        statement="候选人自述负责测试", answer_id="a1", quote="我负责测试", kind="responsibility"
    )
    minutes = Minutes(facts=[fact], gaps=["结果未核实"])
    assert validate_minutes(minutes, [{"id": "a1", "text": "项目中我负责测试。"}]) == minutes
    with pytest.raises(ValueError, match="NO_INTERVIEW"):
        validate_minutes(minutes, [])
    with pytest.raises(ValueError, match="UNSUPPORTED"):
        validate_minutes(minutes, [{"id": "a1", "text": "我们团队取得成功。"}])
    with pytest.raises(ValueError, match="UNSUPPORTED"):
        validate_minutes(minutes, [{"id": "different", "text": "我负责测试"}])


@pytest.mark.parametrize("statement,quote", [("候选人负责测试", " "), (" ", "我负责测试")])
def test_blank_extraction_cannot_be_used_as_evidence(statement, quote):
    minutes = Minutes(
        facts=[MinuteFact(statement=statement, answer_id="a1", quote=quote, kind="other")]
    )
    with pytest.raises(ValueError, match="UNSUPPORTED"):
        validate_minutes(minutes, [{"id": "a1", "text": "我负责测试 。"}])


@pytest.mark.parametrize("fault", [None, "invented", "other_answer", "duplicate", "missing"])
def test_indicator_links_to_exact_facts_and_preserves_both_directions(fault):
    from app.modules.outreach.minutes import evidence_matrix

    answers = [
        {
            "id": "a1",
            "text": "我执行访谈。我没负责设计。如果再做会先试访。",
            "question": {"id": "Q1", "dimension_id": "research"},
            "source_mode": "manual",
        },
        {"id": "a2", "text": "其他", "question": {"id": "Q2"}},
    ]
    facts = [
        {
            "evidence_id": key,
            "answer_id": "a1",
            "statement": quote,
            "quote": quote,
            "kind": "responsibility",
            "evidence_kind": kind,
            "evidence_direction": direction,
        }
        for key, quote, kind, direction in [
            ("EV1", "我执行访谈", "PAST_BEHAVIOR", "SUPPORTING"),
            ("EV2", "我没负责设计", "FACT_ONLY", "LIMITING"),
            ("EV3", "如果再做会先试访", "SITUATIONAL", "NEUTRAL"),
        ]
    ]
    row = {
        "dimension_id": "research",
        "indicator_ref": "dimensions[0].indicators",
        "answer_ids": ["a1"],
        "evidence_ids": ["EV1", "EV2", "EV3"],
        "evidence_sufficiency": "PARTIAL",
        "sufficiency_reason": "有执行和职责边界，缺结果",
        "gaps": ["缺结果"],
    }
    definitions = [
        {
            "dimension_id": "research",
            "indicator_ref": row["indicator_ref"],
            "indicator_text": "研究行动与职责边界",
        }
    ]
    if fault == "invented":
        row["evidence_ids"] = ["EV99"]
    elif fault == "other_answer":
        row["answer_ids"] = ["a2"]
    elif fault == "duplicate":
        row["evidence_ids"].append("EV1")
    elif fault == "missing":
        row["evidence_ids"] = []
    if fault is None:
        row.pop("answer_ids")
    minutes = validate_minutes(Minutes(facts=facts, indicator_evidence=[row]), answers)
    if fault:
        with pytest.raises(ValueError, match="INDICATOR_FACT_"):
            validate_indicator_evidence(minutes, definitions, answers, require_fact_links=True)
        return
    validate_indicator_evidence(minutes, definitions, answers, require_fact_links=True)
    matrix = evidence_matrix(minutes, definitions, answers, None)
    dimension = matrix["dimension_coverage"][0]
    indicator = dimension["indicator_evidence"][0]
    assert indicator["answer_ids"] == ["a1"]
    assert indicator["supporting_evidence_ids"] == ["EV1"]
    assert indicator["limiting_evidence_ids"] == ["EV2"]
    assert indicator["situational_evidence_ids"] == ["EV3"]
    assert indicator["question_ids"] == ["Q1"]
    assert dimension["coverage_status"] == "COVERED"
    assert dimension["dimension_evidence_sufficiency"] == "PARTIAL"
    assert matrix["evidence_items"][0]["turn_ids"] == []
    assert matrix["evidence_items"][0]["source_type"] == "ANSWER_RECORD"
