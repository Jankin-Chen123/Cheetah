"""Export implemented local API separately from the full-platform design draft."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    schema = create_app(Settings()).openapi()
    schema["info"]["description"] = (
        "Implemented local integration snapshot. Not the full-platform design contract. "
        "Real model, voice and complete browser acceptance remain unverified."
    )
    target = Path(__file__).resolve().parents[2] / "docs/api/openapi.goal-local.json"
    content = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not target.exists() or target.read_text(encoding="utf8") != content:
            raise SystemExit("Local API snapshot differs; regenerate export_goal_openapi.py")
        print("Local implemented OpenAPI snapshot matches")
    else:
        target.write_text(content, encoding="utf8")
        print("Local implemented OpenAPI snapshot exported")


if __name__ == "__main__":
    main()
