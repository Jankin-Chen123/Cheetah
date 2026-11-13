from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings


class Base(DeclarativeBase):
    """Shared metadata; business models are added by their owning module."""


@lru_cache(maxsize=4)
def get_engine(database_url: str) -> Engine:
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=0,
        connect_args={"connect_timeout": 3},
    )


def check_database(settings: Settings) -> bool:
    if settings.database_url is None:
        return False
    engine = get_engine(settings.database_url.get_secret_value())
    with engine.connect() as connection:
        return connection.execute(text("SELECT 1")).scalar_one() == 1
