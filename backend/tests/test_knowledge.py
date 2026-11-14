"""Behavior checks; SQLite here does not constitute PostgreSQL acceptance."""

import zipfile

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.modules.outreach.knowledge import MethodDocument, MethodEntry, import_document, retrieve


def write_document(path, body):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{body}</w:t></w:r></w:p></w:body></w:document>",
        )


def test_import_review_version_and_provenance(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    path = tmp_path / "fictional.docx"
    write_document(path, "虚构方法：请描述个人职责与结果？")
    with Session(engine) as session, session.begin():
        original, count = import_document(session, path)
        assert count == 1
        assert import_document(session, path) == (original, 0)
        assert retrieve(session, {"responsibility"}) == []
        preview = retrieve(session, {"responsibility"}, preview=True)
        assert preview[0]["source"]["paragraph"] == 1
        assert preview[0]["source"]["version"] == 1
        entry = session.get(MethodEntry, preview[0]["entry_id"])
        entry.review_status = "approved"
        session.flush()
        assert len(retrieve(session, {"responsibility"})) == 1
        write_document(path, "虚构新方法：请说明职责边界？")
        revised, count = import_document(session, path)
        assert revised != original and count == 1
        assert session.get(MethodDocument, revised).version == 2
        assert retrieve(session, {"responsibility"}) == []
        assert not entry.enabled
        entry.enabled = True
        session.flush()
        assert retrieve(session, {"responsibility"}) == []
        assert len(list(session.scalars(select(MethodEntry)))) == 2
        assert retrieve(session, {"responsibility"}, preview=True)[0]["source"]["version"] == 2
