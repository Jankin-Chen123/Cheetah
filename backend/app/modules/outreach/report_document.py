"""Editable Word export of the immutable, approved customer report text."""

from io import BytesIO
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile


def _table(rows):
    """Render the saved Markdown table as editable Word cells."""
    width = 10080 // len(rows[0])
    result = ['<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/>', "<w:tblBorders>"]
    result.extend(
        f'<w:{edge} w:val="single" w:sz="4" w:color="B8B8B8"/>'
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV")
    )
    result.append("</w:tblBorders></w:tblPr><w:tblGrid>")
    result.extend(f'<w:gridCol w:w="{width}"/>' for _ in rows[0])
    result.append("</w:tblGrid>")
    for index, row in enumerate(rows):
        result.append(
            "<w:tr><w:trPr><w:cantSplit/>" + ("<w:tblHeader/>" if index == 0 else "") + "</w:trPr>"
        )
        for cell in row:
            cell = "".join(c for c in cell if ord(c) >= 32 or c == "\t")
            result.append(
                f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/></w:tcPr>'
                "<w:p><w:r>"
                + ("<w:rPr><w:b/></w:rPr>" if index == 0 else "")
                + f'<w:t xml:space="preserve">{escape(cell)}</w:t></w:r></w:p></w:tc>'
            )
        result.append("</w:tr>")
    result.append("</w:tbl>")
    return "".join(result)


def report_docx(markdown: str) -> bytes:
    paragraphs = []
    table_rows = []
    for line in markdown.splitlines():
        if not line.strip():
            continue
        if line.startswith("|") and line.endswith("|"):
            cells = [cell.strip().replace("&#124;", "|") for cell in line[1:-1].split("|")]
            if all(cell and set(cell) <= {"-", ":"} for cell in cells):
                continue
            if table_rows and len(cells) != len(table_rows[0]):
                paragraphs.append(_table(table_rows))
                table_rows = []
            table_rows.append(cells)
            continue
        if table_rows:
            paragraphs.append(_table(table_rows))
            table_rows = []
        if not line.strip():
            continue
        style = "Normal"
        if line.startswith("# "):
            style, line = "Title", line[2:]
        elif line.startswith("## "):
            style, line = "Heading1", line[3:]
        elif line.startswith("### "):
            style, line = "Heading2", line[4:]
        elif line.startswith("> "):
            line = line[2:]
        line = "".join(c for c in line if ord(c) >= 32 or c == "\t")
        paragraphs.append(
            f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
            f'<w:r><w:t xml:space="preserve">{escape(line)}</w:t></w:r></w:p>'
        )
    if table_rows:
        paragraphs.append(_table(table_rows))
    namespace = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    document = (
        f'<?xml version="1.0" encoding="UTF-8"?><w:document {namespace}><w:body>'
        + "".join(paragraphs)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1080" w:right="1080" w:bottom="1080" w:left="1080"/>'
        "</w:sectPr></w:body></w:document>"
    )
    styles = f"""<?xml version="1.0" encoding="UTF-8"?><w:styles {namespace}>
    <w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:eastAsia="微软雅黑"/>
    <w:sz w:val="22"/><w:color w:val="000000"/></w:rPr></w:rPrDefault>
    <w:pPrDefault><w:pPr><w:spacing w:after="140" w:line="300" w:lineRule="auto"/>
    </w:pPr></w:pPrDefault></w:docDefaults>
    <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
    <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/>
    <w:basedOn w:val="Normal"/><w:pPr><w:keepNext/></w:pPr><w:rPr><w:b/><w:sz w:val="36"/>
    <w:color w:val="000000"/></w:rPr></w:style>
    <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>
    <w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="260"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="28"/><w:color w:val="000000"/></w:rPr></w:style>
    <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/>
    <w:basedOn w:val="Normal"/><w:pPr><w:keepNext/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="24"/><w:color w:val="000000"/></w:rPr></w:style>
    </w:styles>"""
    content_types = """<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
    <Default Extension="rels"
    ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
    <Default Extension="xml" ContentType="application/xml"/>
    <Override PartName="/word/document.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
    <Override PartName="/word/styles.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
    </Types>"""
    relations = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="word/document.xml"/>
    </Relationships>"""
    style_relation = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"
    Target="styles.xml"/>
    </Relationships>"""
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        for name, content in {
            "[Content_Types].xml": content_types,
            "_rels/.rels": relations,
            "word/document.xml": document,
            "word/styles.xml": styles,
            "word/_rels/document.xml.rels": style_relation,
        }.items():
            package.writestr(name, content.encode("utf-8"))
    return output.getvalue()
