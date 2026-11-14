"""Export the public handoff schema, or verify the committed copy in CI."""

import argparse
import json
from pathlib import Path

from app.core.contracts import ScreeningPassedEvent, ScreeningPassedEventV11


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2] / "docs/contracts"
    for version, model in (("v1", ScreeningPassedEvent), ("v1.1", ScreeningPassedEventV11)):
        target = root / f"screening-passed.{version}.schema.json"
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        content = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != content:
                raise SystemExit("Contract schema is stale. Run the exporter without --check.")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    print("Contract schemas match the Python models." if args.check else "Exported event schemas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
