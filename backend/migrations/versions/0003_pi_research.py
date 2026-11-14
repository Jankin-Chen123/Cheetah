"""Persist Pi conversations and externally executed research actions."""

import sqlalchemy as sa
from alembic import op

revision = "0003_pi_research"
down_revision = "0002_bounded_research"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "research_runs",
        sa.Column("task_id", sa.String(64), primary_key=True),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("messages", sa.JSON(), nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "research_actions",
        sa.Column("task_id", sa.String(64), primary_key=True),
        sa.Column("action_id", sa.String(128), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("actual_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("research_actions")
    op.drop_table("research_runs")
