"""Persist local development login sessions."""

import sqlalchemy as sa
from alembic import op

revision = "0003_login_sessions"
down_revision = "0002_outreach_state"
branch_labels = None
depends_on = None


def upgrade():
    # The platform root may already have created its canonical session table.
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("login_sessions"):
        columns = {column["name"] for column in inspector.get_columns("login_sessions")}
        if columns != {"token_hash", "user_id", "expires_at"}:
            raise RuntimeError("Unexpected existing session schema; review before migrating")
        return

    op.create_table(
        "login_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("csrf", sa.String(128), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.Integer, nullable=False),
    )


def downgrade():
    if not sa.inspect(op.get_bind()).has_table("login_sessions"):
        return
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("login_sessions")}
    if "csrf" in columns:
        op.drop_table("login_sessions")
