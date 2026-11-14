"""Import a locally reviewed extraction bundle as pending structured methods."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import get_engine  # noqa: E402
from app.modules.outreach.curation import CuratedMethod  # noqa: E402
from app.modules.outreach.knowledge import (  # noqa: E402
    MethodEntry,
    extract_paragraphs,
    import_document,
)


def import_bundle(session, payload, source_directory):
    filename = payload["filename"]
    if Path(filename).name != filename:
        raise ValueError("Source must be a filename, not a path")
    source = source_directory / filename
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != payload["document_sha256"]:
        raise ValueError("Source hash mismatch")
    paragraphs = dict(extract_paragraphs(source))
    version = payload["extraction_version"]
    if not isinstance(version, int) or version < 1:
        raise ValueError("Positive extraction version required")
    if not 1 <= len(payload["methods"]) <= 100:
        raise ValueError("One to 100 structured methods required")
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(728194)"))
    document_id, _ = import_document(session, source)
    previous = list(
        session.scalars(select(MethodEntry).where(MethodEntry.document_id == document_id))
    )
    latest = max(
        (
            entry.content.get("extraction_version", entry.content.get("method_version", 0))
            for entry in previous
            if entry.content.get("extraction_status") in {"structured_pending_review", "curated"}
        ),
        default=0,
    )
    count = 0
    for position, raw in enumerate(payload["methods"]):
        refs = raw["source_paragraphs"]
        if not refs or any(number not in paragraphs for number in refs):
            raise ValueError("Invalid source paragraphs")
        method = CuratedMethod.model_validate(
            {key: value for key, value in raw.items() if key != "source_paragraphs"}
        )
        identity = f"{document_id}:extraction:{version}:{position}"
        entry_id = hashlib.sha256(identity.encode()).hexdigest()
        content = {
            **method.model_dump(),
            "source_paragraphs": refs,
            "source_text": "\n".join(paragraphs[number] for number in refs),
            "extraction_status": "structured_pending_review",
            "method_version": version,
            "generator": payload.get("generator", {}),
        }
        fingerprint = hashlib.sha256(
            json.dumps(content, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        existing = session.get(MethodEntry, entry_id)
        if existing:
            if (
                existing.content.get(
                    "import_sha256", fingerprint if existing.content == content else None
                )
                != fingerprint
            ):
                raise ValueError("Extraction version content changed; increment extraction_version")
            continue
        content.update(extraction_version=version, import_sha256=fingerprint)
        session.add(
            MethodEntry(
                id=entry_id,
                document_id=document_id,
                paragraph=refs[0],
                content=content,
                review_status="pending",
                enabled=version >= latest,
            )
        )
        count += 1
    if version > latest:
        for entry in previous:
            if entry.content.get("extraction_status") in {"structured_pending_review", "curated"}:
                entry.enabled = False
    session.flush()
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("source_directory", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    if settings.database_url is None:
        parser.error("Database configuration required")
    payload = json.loads(args.bundle.read_text(encoding="utf8"))
    with Session(get_engine(settings.database_url.get_secret_value())) as session, session.begin():
        count = import_bundle(session, payload, args.source_directory)
    print(f"New pending structured methods: {count}; no automatic approval")


if __name__ == "__main__":
    main()
