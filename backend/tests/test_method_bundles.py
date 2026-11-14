import hashlib
import zipfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.modules.outreach.curation import CuratedMethod, curate
from app.modules.outreach.knowledge import retrieve
from scripts.import_method_bundle import import_bundle


def test_structured_bundle_is_idempotent_versioned_and_filtered(tmp_path):
    source = tmp_path / "fictional.docx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>虚构方法：个人职责是什么？</w:t></w:r></w:p></w:body></w:document>",
        )
    method = {
        "topic": "职责核实",
        "dimensions": ["responsibility"],
        "tags": ["responsibility"],
        "trigger_conditions": ["个人职责未知"],
        "question_examples": ["个人职责是什么？"],
        "followup_strategy": "追问个人行动",
        "stop_conditions": ["证据完整或候选人停止"],
        "exceptions": ["缺失保留未知"],
        "conflicts": [],
        "source_paragraphs": [1],
    }
    payload = {
        "filename": source.name,
        "document_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "extraction_version": 1,
        "methods": [method],
    }
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        assert import_bundle(session, payload, tmp_path) == 1
        assert import_bundle(session, payload, tmp_path) == 0
        hits = retrieve(session, {"responsibility"}, preview=True, structured_only=True)
        assert len(hits) == 1
        assert hits[0]["content"]["source_paragraphs"] == [1]
        assert retrieve(session, {"responsibility"}, structured_only=True) == []
        from app.modules.outreach.knowledge import MethodEntry

        entry = session.get(MethodEntry, hits[0]["entry_id"])
        curate(
            entry,
            CuratedMethod.model_validate(
                {k: v for k, v in method.items() if k != "source_paragraphs"}
            ),
            "reviewer",
            True,
        )
        assert import_bundle(session, payload, tmp_path) == 0
        changed = {**payload, "methods": [{**method, "topic": "changed"}]}
        with pytest.raises(ValueError, match="increment extraction_version"):
            import_bundle(session, changed, tmp_path)
        conflict = {
            **payload,
            "extraction_version": 2,
            "methods": [{**method, "conflicts": ["需业务审核冲突"]}],
        }
        assert import_bundle(session, conflict, tmp_path) == 1
        entry.enabled = True  # Re-enabling an older extraction cannot bypass version selection.
        assert retrieve(session, {"responsibility"}, preview=True, structured_only=True) == []
        with pytest.raises(ValueError, match="hash mismatch"):
            import_bundle(session, {**payload, "document_sha256": "incorrect"}, tmp_path)
