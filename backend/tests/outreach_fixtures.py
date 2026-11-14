"""Interview HTTP fixtures use real platform accounts in isolated databases."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import browser_db, hash_password
from app.core.models import Identity
from app.main import create_app


def reviewer_app(engine, settings, *, password="fixture-password"):
    with Session(engine) as db, db.begin():
        if db.scalar(select(Identity).where(Identity.username == "local-reviewer")) is None:
            db.add(
                Identity(
                    id="local-reviewer",
                    username="local-reviewer",
                    display_name="虚构审核人",
                    organization_id="local-development",
                    password_hash=hash_password(password),
                )
            )
    app = create_app(settings)

    def isolated_db():
        with Session(engine) as db, db.begin():
            yield db

    app.dependency_overrides[browser_db] = isolated_db
    return app
