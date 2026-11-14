"""Load the supplied prompts as pinned application resources with explicit host policy."""

import hashlib
import json
from pathlib import Path

RESOURCES = Path(__file__).resolve().parents[3] / "agents/intake/resources"
AGENTS = {
    "job_analysis": "A01",
    "interview_standard": "A02",
    "screening_standard": "A05",
    "resume_parse": "A04",
    "screening": "A05",
}


def source_prompt(code):
    manifest = json.loads((RESOURCES / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest[code]
    data = (RESOURCES / entry["resource"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise ValueError("Agent resource fingerprint mismatch")
    return data.decode("utf-8-sig")


def resource_fingerprint():
    digest = hashlib.sha256()
    digest.update((RESOURCES / "manifest.json").read_bytes())
    for code in ("A01", "A02", "A03", "A04", "A05"):
        digest.update(source_prompt(code).encode())
    for path in sorted(RESOURCES.glob("*-adapter.md")):
        digest.update(path.read_bytes())
    digest.update((RESOURCES / "execution-policy.md").read_bytes())
    for name in ("agent_prompts.py", "form_contracts.py", "schemas.py"):
        digest.update((Path(__file__).parent / name).read_bytes())
    return digest.hexdigest()


def system_prompt(kind, schema):
    policy = (RESOURCES / "execution-policy.md").read_text(encoding="utf-8")
    adapter = (RESOURCES / (kind + "-adapter.md")).read_text(encoding="utf-8")
    return "\n".join(
        [
            policy,
            source_prompt(AGENTS[kind]),
            adapter,
            json.dumps(schema.model_json_schema(), ensure_ascii=False),
        ]
    )
