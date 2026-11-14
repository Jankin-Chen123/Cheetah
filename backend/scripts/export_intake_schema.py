"""Export the material-driven A01/A02/A04/A05 contracts from their Python owners."""

import argparse
import json
from pathlib import Path

from app.modules.intake.form_contracts import (
    JobForm,
    ResumeForm,
    ScoreSummary,
    ScreeningAssessment,
    ScreeningRubric,
)
from app.modules.intake.schemas import InterviewStandard, ScreeningStandard


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2] / "docs/contracts"
    models = {
        "a01-job-form": JobForm,
        "a02-interview-standard": InterviewStandard,
        "a04-resume-form": ResumeForm,
        "a05-screening-standard": ScreeningStandard,
        "a05-screening-rubric": ScreeningRubric,
        "a05-screening-assessment": ScreeningAssessment,
        "a05-score-summary": ScoreSummary,
    }
    for name, model in models.items():
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            **model.model_json_schema(),
        }
        content = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
        path = root / f"{name}.v2.schema.json"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                raise SystemExit("Intake form contract is stale; run exporter without --check")
        else:
            path.write_text(content, encoding="utf-8")
    print("Intake form contracts match models" if args.check else "Exported intake form contracts")


if __name__ == "__main__":
    main()
