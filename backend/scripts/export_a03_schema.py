"""Export A03 objects, reports and tool contracts from their owning Python models."""

import argparse
import json
from pathlib import Path

from app.modules.intake.a03_contracts import TOOL_MODELS, ResearchReport
from app.modules.intake.schemas import ResumeProfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2] / "docs/contracts"
    entries = {"a04-profile": ResumeProfile, "a03-report": ResearchReport}
    entries.update(
        {"a03-tool-" + name.replace("_", "-"): model for name, model in TOOL_MODELS.items()}
    )
    for name, model in entries.items():
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            **model.model_json_schema(),
        }
        content = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
        target = root / f"{name}.v1.schema.json"
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != content:
                raise SystemExit("A03 contract is stale; run exporter without --check")
        else:
            target.write_text(content, encoding="utf-8")
    print("A03 contract matches models" if args.check else "Exported A03 contracts")


if __name__ == "__main__":
    main()
