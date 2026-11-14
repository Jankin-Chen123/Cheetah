from types import SimpleNamespace

from app.modules.outreach.handoff import preparation_metadata


class FakeSession:
    def __init__(self, artifact):
        self.artifact = artifact

    def get(self, model, identity):
        return self.artifact


def test_handoff_does_not_invent_versions_or_cross_case_references():
    case = SimpleNamespace(id="case", session_data={"outline_id": "outline"})
    wrong = SimpleNamespace(case_id="other", type="D07")
    result = preparation_metadata(FakeSession(wrong), case)
    assert result["preparation_refs"] == {}
    assert result["extraction_limitations"]


def test_handoff_uses_immutable_outline_standard_not_current_binding():
    original = {"standard": {"version": 1}}
    outline = SimpleNamespace(
        id="outline",
        case_id="case",
        type="D07",
        version=3,
        valid=False,
        content={
            "questions": [{"id": "q1", "dimension_id": "d1"}, {"id": "q2", "dimension_id": "d2"}]
        },
        provenance={"job_interview_standard": original},
    )
    case = SimpleNamespace(
        id="case",
        session_data={
            "outline_id": "outline",
            "answers": [{"id": "a1", "question": {"id": "q1"}, "turn_id": "t1"}],
            "job_interview_standard": {"standard": {"version": 2}},
        },
    )
    result = preparation_metadata(FakeSession(outline), case)
    assert result["preparation_refs"]["D02"] == original
    assert result["preparation_refs"]["D07"]["valid"] is False
    assert any("不证明" in note for note in result["extraction_limitations"])

    coverage = result["question_execution_coverage"]
    assert coverage[0]["answer_ids"] == ["a1"]
    assert coverage[0]["turn_ids"] == ["t1"]
    assert coverage[1]["execution_status"] == "NO_ANSWER_RECORDED"
    assert coverage[1]["answer_ids"] == []
