"""Version-specific report review and export audit."""

import sqlalchemy as sa
from alembic import op

revision = "0004_report_audit"
down_revision = "0003_login_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "report_audits",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("report_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("detail", sa.JSON, nullable=False),
        sa.UniqueConstraint("report_id", "action", "request_id"),
    )
    op.create_index("ix_report_audits_report_id", "report_audits", ["report_id"])


def downgrade():
    op.drop_table("report_audits")
