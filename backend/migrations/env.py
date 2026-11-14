from alembic import context

from app.core import models as core_models  # noqa: F401 -- register shared tables
from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.modules.outreach import (
    knowledge,  # noqa: F401
    models,  # noqa: F401
)

target_metadata = Base.metadata
provided_connection = context.config.attributes.get("connection")
settings = get_settings()
if provided_connection is None and settings.database_url is None:
    raise RuntimeError("CHEETA_DATABASE_URL must be configured for migrations")

if context.is_offline_mode():
    context.configure(
        url=settings.database_url.get_secret_value(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
elif provided_connection is not None:
    context.configure(connection=provided_connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()
else:
    with get_engine(settings.database_url.get_secret_value()).connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
