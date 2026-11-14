"""Persist local development login sessions."""

import sqlalchemy as sa
from alembic import op

revision = "0003_login_sessions"
down_revision = "0002_outreach_state"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "login_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("csrf", sa.String(128), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.Integer, nullable=False),
    )


def downgrade():
    op.drop_table("login_sessions")
