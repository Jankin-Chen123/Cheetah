"""Provision a local account explicitly. No built-in or default credentials."""

import argparse
import getpass

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.core.config import get_settings
from app.core.database import get_engine
from app.core.models import Identity


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("--organization", required=True)
    parser.add_argument("--display-name", required=True)
    args = parser.parse_args()
    if not (
        1 <= len(args.username.strip()) <= 100
        and 1 <= len(args.organization.strip()) <= 64
        and 1 <= len(args.display_name.strip()) <= 100
    ):
        raise SystemExit("Invalid account field length")
    password = getpass.getpass("Password (at least 12 characters): ")
    if len(password) < 12 or password != getpass.getpass("Confirm password: "):
        raise SystemExit("Password too short or confirmation does not match")
    settings = get_settings()
    if settings.database_url is None:
        raise SystemExit("Configure CHEETA_DATABASE_URL and run migrations first")
    with Session(get_engine(settings.database_url.get_secret_value())) as db, db.begin():
        if db.scalar(select(Identity).where(Identity.username == args.username)):
            raise SystemExit("User already exists; no account was modified")
        db.add(
            Identity(
                username=args.username,
                organization_id=args.organization,
                display_name=args.display_name,
                password_hash=hash_password(password),
            )
        )
    print("Account created")


if __name__ == "__main__":
    try:
        main()
    except SQLAlchemyError:
        raise SystemExit(
            "Account not created; check database configuration and migrations"
        ) from None
