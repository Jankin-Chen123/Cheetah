"""Persistent model step execution receipts."""

import sqlalchemy as sa
from alembic import op

revision = "0005_model_steps"
down_revision = "0004_report_audit"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "model_steps",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("step", sa.String(64), nullable=False),
        sa.Column("input_revision", sa.Integer, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("detail", sa.JSON, nullable=False),
        sa.UniqueConstraint("case_id", "step", "input_revision"),
    )
    op.create_index("ix_model_steps_case_id", "model_steps", ["case_id"])


def downgrade():
    op.drop_table("model_steps")
