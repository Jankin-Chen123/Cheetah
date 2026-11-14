from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile

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
