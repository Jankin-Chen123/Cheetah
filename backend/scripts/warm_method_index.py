"""Warm versioned method embedding cache before accepting practice interviews."""

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import get_engine  # noqa: E402
from app.modules.outreach.knowledge import retrieve  # noqa: E402
from app.modules.outreach.retrieval import cached_vector, method_text  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if args.preview and settings.environment != "development":
        parser.error("Preview cache warming is development only")
    if not settings.database_url:
        parser.error("Database required")
    engine = get_engine(settings.database_url.get_secret_value())
    with Session(engine) as session:
        methods = retrieve(session, None, preview=args.preview, structured_only=True, limit=100)
    with ThreadPoolExecutor(max_workers=4) as pool:
        vectors = list(pool.map(lambda item: cached_vector(settings, method_text(item)), methods))
    print(f"Indexed {len(vectors)} eligible method entries. No review status was changed.")


if __name__ == "__main__":
    main()
