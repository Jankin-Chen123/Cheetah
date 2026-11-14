from functools import lru_cache

from fastapi import Request
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session

from app.core.config import Settings
from app.core.errors import DomainError


class Base(DeclarativeBase):
    """Shared metadata; business models are added by their owning module."""


@lru_cache(maxsize=4)
def get_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        # SQLite is only for isolated tests and local development, not multi-worker deployment.
        return create_engine(
            database_url, connect_args={"check_same_thread": False}, hide_parameters=True
        )
    return create_engine(
        database_url,
        hide_parameters=True,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=0,
        connect_args={"connect_timeout": 3},
    )


def get_db(request: Request):
    settings = request.app.state.settings
    if settings.database_url is None:
        raise DomainError("DEPENDENCY_NOT_READY", "尚未配置数据库", 503)
    with Session(get_engine(settings.database_url.get_secret_value())) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def check_database(settings: Settings) -> bool:
    if settings.database_url is None:
        return False
    engine = get_engine(settings.database_url.get_secret_value())
    with engine.connect() as connection:
        return connection.execute(text("SELECT 1")).scalar_one() == 1
