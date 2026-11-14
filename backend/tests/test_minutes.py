import pytest

from app.modules.outreach.minutes import MinuteFact, Minutes, validate_minutes


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
