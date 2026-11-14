"""Persistent outreach cases, event receipts and artifact versions."""

import sqlalchemy as sa
from alembic import op

revision = "0002_outreach_state"
down_revision = "0001_method_library"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "outreach_cases",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("application_id", sa.String(128), nullable=False),
        sa.Column("candidate_id", sa.String(128), nullable=False),
        sa.Column("job_id", sa.String(128), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("stop_status", sa.String(24), nullable=False),
        sa.Column("snapshot", sa.JSON, nullable=False),
        sa.Column("session_data", sa.JSON, nullable=False),
        sa.UniqueConstraint("organization_id", "application_id"),
    )
    op.create_index("ix_outreach_cases_organization_id", "outreach_cases", ["organization_id"])
    op.create_table(
        "outreach_received_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("organization_id", sa.String(128), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.UniqueConstraint("organization_id", "event_id"),
    )
    op.create_table(
        "outreach_artifacts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("type", sa.String(3), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("valid", sa.Boolean, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("review_status", sa.String(24), nullable=False),
        sa.Column("content", sa.JSON, nullable=False),
        sa.Column("provenance", sa.JSON, nullable=False),
        sa.Column("input_refs", sa.JSON, nullable=False),
        sa.UniqueConstraint("case_id", "type", "version"),
    )
    op.create_index("ix_outreach_artifacts_case_id", "outreach_artifacts", ["case_id"])


def downgrade():
    for name in ("outreach_artifacts", "outreach_received_events", "outreach_cases"):
        op.drop_table(name)
