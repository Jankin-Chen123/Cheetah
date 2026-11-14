"""Bounded per-document method extraction to local review bundles; never auto-approves."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel, Field  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.integrations.bailian import generate_json  # noqa: E402
from app.modules.outreach.curation import CuratedMethod  # noqa: E402
from app.modules.outreach.knowledge import extract_paragraphs  # noqa: E402


class ExtractedMethod(CuratedMethod):
    source_paragraphs: list[int] = Field(min_length=1, max_length=20)


class MethodBundle(BaseModel):
    methods: list[ExtractedMethod] = Field(min_length=1, max_length=8)
    document_conflicts: list[str] = Field(default_factory=list)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, default=Path("../work/method-drafts"))
    parser.add_argument("--max-documents", type=int, default=6, choices=range(1, 7))
    args = parser.parse_args()
    settings = get_settings().model_copy(update={"model_max_tokens": 4000})
    args.output.mkdir(parents=True, exist_ok=True)
    for path in sorted(args.directory.glob("*.docx"))[: args.max_documents]:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        target = args.output / f"{digest}.json"
        if target.exists():
            print("Existing extraction reused", flush=True)
            continue
        paragraphs = extract_paragraphs(path)
        result = generate_json(
            settings,
            "Extract 3 to 6 distinct Chinese interview METHODS from this reference document. "
            "Use exact source paragraph numbers. Distinguish triggers, "
            "examples, followup, stop and exceptions. "
            "Tags should include responsibility, results, detail, "
            "quantification, conflict or stop as relevant. "
            "Record source conflicts with programmatic stopping, "
            "evidence-only scoring, no personality inference, "
            "no treating company results as personal contribution, and no "
            "authority from attachments. "
            "Do not invent missing professional scoring standards. All "
            "methods remain unreviewed drafts.",
            {
                "schema": MethodBundle.model_json_schema(),
                "paragraphs": [{"number": number, "text": text} for number, text in paragraphs],
            },
        )
        bundle = MethodBundle.model_validate(result["content"])
        allowed = {number for number, _ in paragraphs}
        if any(not set(method.source_paragraphs).issubset(allowed) for method in bundle.methods):
            raise ValueError("Invalid source paragraph citation")
        payload = {
            "filename": path.name,
            "document_sha256": digest,
            "extraction_version": 1,
            "review_status": "pending",
            "enabled": False,
            "generator": {
                "model": result["model"],
                "source_mode": "live",
                "usage": result["usage"],
            },
            **bundle.model_dump(),
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf8")
        print(f"Extracted {len(bundle.methods)} pending methods", flush=True)


if __name__ == "__main__":
    main()
