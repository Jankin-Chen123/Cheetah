"""Local method library. Imported material is unreviewed until explicitly approved."""

import hashlib
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.database import Base
from app.modules.outreach.extraction import draft_method


class MethodDocument(Base):
    __tablename__ = "method_documents"
    __table_args__ = (UniqueConstraint("filename", "sha256"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)


class MethodEntry(Base):
    __tablename__ = "method_entries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("method_documents.id"), index=True)
    paragraph: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSON)
    review_status: Mapped[str] = mapped_column(String(24), default="pending")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


def extract_paragraphs(path: Path) -> list[tuple[int, str]]:
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    return [
        (i, text)
        for i, paragraph in enumerate(root.findall(".//w:p", ns), 1)
        if (text := "".join(t.text or "" for t in paragraph.findall(".//w:t", ns)).strip())
    ]


def import_document(session: Session, path: Path) -> tuple[str, int]:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(sql_text("SELECT pg_advisory_xact_lock(728194)"))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    document_id = hashlib.sha256(f"{path.name}:{digest}".encode()).hexdigest()
    paragraphs = extract_paragraphs(path)
    if session.get(MethodDocument, document_id):
        for position, (paragraph, _) in enumerate(paragraphs):
            entry_id = hashlib.sha256(f"{document_id}:{paragraph}".encode()).hexdigest()
            entry = session.get(MethodEntry, entry_id)
            if (
                entry
                and entry.review_status == "pending"
                and entry.content.get("extraction_status") == "raw_requires_curation"
            ):
                entry.content = {**entry.content, **draft_method(paragraphs, position)}
        return document_id, 0
    # Serialize imports in the caller's transaction on PostgreSQL.
    previous = list(
        session.scalars(
            select(MethodDocument).where(MethodDocument.filename == path.name).with_for_update()
        )
    )
    version = max((doc.version for doc in previous), default=0) + 1
    for doc in previous:
        for entry in session.scalars(select(MethodEntry).where(MethodEntry.document_id == doc.id)):
            entry.enabled = False
    session.add(MethodDocument(id=document_id, filename=path.name, sha256=digest, version=version))
    tags_by_word = {
        "责任": "responsibility",
        "职责": "responsibility",
        "成果": "results",
        "结果": "results",
        "数字": "quantification",
        "细节": "detail",
        "停止": "stop",
        "矛盾": "conflict",
        "STAR": "star",
    }
    count = 0
    for position, (paragraph, text) in enumerate(paragraphs):
        tags = [tag for word, tag in tags_by_word.items() if word in text]
        session.add(
            MethodEntry(
                id=hashlib.sha256(f"{document_id}:{paragraph}".encode()).hexdigest(),
                document_id=document_id,
                paragraph=paragraph,
                content={
                    "source_text": text,
                    "tags": sorted(set(tags)),
                    "topic": path.stem,
                    "dimensions": sorted(set(tags)),
                    "trigger_conditions": [],
                    "question_examples": [text] if chr(0xFF1F) in text else [],
                    "followup_strategy": None,
                    "stop_conditions": [],
                    "exceptions": [],
                    "extraction_status": "raw_requires_curation",
                    "conflicts": [],
                    **draft_method(paragraphs, position),
                },
            )
        )
        count += 1
    session.flush()
    return document_id, count


def retrieve(
    session: Session,
    tags: set[str] | None,
    *,
    preview: bool = False,
    limit: int = 8,
    structured_only: bool = False,
):
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    query = select(MethodEntry).where(MethodEntry.enabled.is_(True))
    if not preview:
        query = query.where(MethodEntry.review_status == "approved")
    latest_extractions: dict[str, int] = {}
    for method in session.scalars(select(MethodEntry)):
        if method.content.get("extraction_status") == "structured_pending_review" or (
            method.content.get("extraction_status") == "curated"
            and "extraction_version" in method.content
        ):
            version = method.content.get(
                "extraction_version", method.content.get("method_version", 0)
            )
            latest_extractions[method.document_id] = max(
                latest_extractions.get(method.document_id, 0), version
            )
    matches = []
    for entry in session.scalars(query):
        extraction_version = entry.content.get("extraction_version")
        if (
            extraction_version is None
            and entry.content.get("extraction_status") == "structured_pending_review"
        ):
            extraction_version = entry.content.get("method_version", 0)
        if extraction_version is not None and extraction_version < latest_extractions.get(
            entry.document_id, 0
        ):
            continue
        if structured_only and entry.content.get("extraction_status") not in {
            "structured_pending_review",
            "curated",
        }:
            continue
        if entry.content.get("conflicts"):
            continue
        overlap = (
            tags.intersection(entry.content["tags"])
            if tags is not None
            else set(entry.content["tags"])
        )
        if overlap:
            doc = session.get(MethodDocument, entry.document_id)
            newest = session.scalar(
                select(MethodDocument.version)
                .where(MethodDocument.filename == doc.filename)
                .order_by(MethodDocument.version.desc())
                .limit(1)
            )
            if doc.version != newest:
                continue
            matches.append(
                {
                    "entry_id": entry.id,
                    "content": entry.content,
                    "matched_tags": sorted(overlap),
                    "preview": preview,
                    "review_status": entry.review_status,
                    "source": {
                        "filename": doc.filename,
                        "sha256": doc.sha256,
                        "version": doc.version,
                        "paragraph": entry.paragraph,
                    },
                }
            )
    return sorted(matches, key=lambda item: (-len(item["matched_tags"]), item["entry_id"]))[:limit]
