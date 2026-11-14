from io import BytesIO
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from app.modules.outreach.evaluation_document import evaluation_markdown
from app.modules.outreach.report_document import report_docx


def test_word_table_is_editable_and_preserves_escaped_values():
    data = report_docx(
        "# 虚构资料\n\n| 时间 | 公司 |\n| --- | --- |\n| 2023年 | 甲&#124;乙 & 丙 |\n\n正文"
    )
    with ZipFile(BytesIO(data)) as package:
        doc = ET.fromstring(package.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    rows = doc.findall(".//w:tbl/w:tr", ns)
    assert len(rows) == 2
    assert rows[0].find("w:trPr/w:tblHeader", ns) is not None
    assert [t.text for t in rows[1].findall(".//w:t", ns)] == ["2023年", "甲|乙 & 丙"]
    assert doc.findall(".//w:t", ns)[-1].text == "正文"


def test_internal_evaluation_word_links_scoring_to_saved_quotes():
    artifact = SimpleNamespace(
        version=2,
        provenance={},
        input_refs=[{"id": "minutes", "version": 4}],
        content={
            "dimensions": [{"dimension_id": "d1", "fact_evidence_ids": ["EV1"]}],
            "indicator_evidence": [
                {
                    "dimension_id": "d1",
                    "indicator_ref": "dimensions[0].indicators",
                    "evidence_sufficiency": "PARTIAL",
                }
            ],
            "evidence_items": [
                {
                    "evidence_id": "EV1",
                    "quote": "我负责独立验收",
                    "answer_id": "a1",
                    "answer_version": 3,
                    "turn_ids": ["turn-1"],
                },
                {"evidence_id": "EV2", "quote": "没有用于打分的原话"},
            ],
        },
    )
    with ZipFile(BytesIO(report_docx(evaluation_markdown(artifact)))) as package:
        xml = package.read("word/document.xml").decode()
    assert "EV1 候选人原话：“我负责独立验收”" in xml
    assert "回答：a1 · v3" in xml and "轮次：turn-1" in xml
    assert "证据充分性：PARTIAL" in xml and "总分：未形成" in xml
    assert "没有用于打分的原话" not in xml
