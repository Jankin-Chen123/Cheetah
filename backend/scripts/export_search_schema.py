"""Export the normalized provider-facing search contract, independent from browser HTTP DTOs."""

import argparse
import json
from pathlib import Path

from app.integrations.search import SearchRequest, SearchResult


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2] / "docs/contracts"
    for name, model in (("search-request", SearchRequest), ("search-result", SearchResult)):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            **model.model_json_schema(),
        }
        content = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
        target = root / f"{name}.v1.schema.json"
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != content:
                raise SystemExit("Search contract is stale; run exporter without --check")
        else:
            target.write_text(content, encoding="utf-8")
    print("Search contract matches models" if args.check else "Exported normalized search contract")


if __name__ == "__main__":
    main()
