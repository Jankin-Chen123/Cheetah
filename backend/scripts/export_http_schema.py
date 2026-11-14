"""Export the actual HTTP API; planned B routes remain in the separate design draft."""

import argparse
import json
from pathlib import Path

from app.core.config import Settings
from app.main import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = Path(__file__).resolve().parents[2] / "docs/api/openapi.implemented.v1.json"
    schema = create_app(Settings(_env_file=None, environment="test")).openapi()
    content = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not target.exists() or target.read_text(encoding="utf-8") != content:
            raise SystemExit("HTTP schema is stale. Run this exporter without --check.")
        print("HTTP schema matches the application")
    else:
        target.write_text(content, encoding="utf-8")
        print("Exported implemented HTTP schema")


if __name__ == "__main__":
    main()
