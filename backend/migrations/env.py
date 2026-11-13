from alembic import context

from app.core.config import get_settings
from app.core.database import Base, get_engine

settings = get_settings()
if settings.database_url is None:
    raise RuntimeError("CHEETA_DATABASE_URL must be configured for migrations")

target_metadata = Base.metadata

if context.is_offline_mode():
    context.configure(
        url=settings.database_url.get_secret_value(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    with get_engine(settings.database_url.get_secret_value()).connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
