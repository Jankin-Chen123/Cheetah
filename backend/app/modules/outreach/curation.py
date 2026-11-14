"""Explicit method curation, separated from raw document import."""

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field

from app.modules.outreach.knowledge import MethodEntry


class CuratedMethod(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str = Field(min_length=1, max_length=200)
    dimensions: list[str] = Field(min_length=1, max_length=20)
    tags: list[str] = Field(min_length=1, max_length=20)
    trigger_conditions: list[str] = Field(min_length=1, max_length=20)
    question_examples: list[str] = Field(min_length=1, max_length=20)
    followup_strategy: str = Field(min_length=1, max_length=4000)
    stop_conditions: list[str] = Field(min_length=1, max_length=20)
    exceptions: list[str] = Field(min_length=1, max_length=20)
    conflicts: list[str] = Field(default_factory=list, max_length=20)


def curate(entry: MethodEntry, method: CuratedMethod, reviewer: str, approve: bool):
    if entry.review_status == "approved":
        raise ValueError("Approved content is immutable; import a new source version")
    if approve and method.conflicts:
        raise ValueError("Unresolved method conflicts require review")
    source_metadata = dict(entry.content)
    if source_metadata.get("extraction_status") == "structured_pending_review":
        source_metadata.setdefault(
            "import_sha256",
            hashlib.sha256(
                json.dumps(
                    {
                        key: value
                        for key, value in entry.content.items()
                        if key not in {"import_sha256", "extraction_version"}
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
        )
        source_metadata.setdefault("extraction_version", entry.content.get("method_version", 1))
    entry.content = {
        **source_metadata,
        **method.model_dump(),
        "source_text": entry.content["source_text"],
        "extraction_status": "curated",
        "reviewer_id": reviewer,
        "method_version": entry.content.get("method_version", 0) + 1,
    }
    entry.review_status = "approved" if approve else "pending"
