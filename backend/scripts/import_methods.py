"""Import local DOCX files without enabling them as approved business rules."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import get_engine  # noqa: E402
from app.modules.outreach.knowledge import import_document  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    if settings.database_url is None:
        parser.error("CHEETA_DATABASE_URL must be configured")
    with Session(get_engine(settings.database_url.get_secret_value())) as session:
        with session.begin():
            # A single transaction and lock makes repeat/concurrent local imports deterministic.
            from sqlalchemy import text

            session.execute(text("SELECT pg_advisory_xact_lock(728194)"))
            counts = [
                import_document(session, path)[1] for path in sorted(args.directory.glob("*.docx"))
            ]
    print(f"Documents scanned: {len(counts)}; new pending paragraphs: {sum(counts)}")


if __name__ == "__main__":
    main()
