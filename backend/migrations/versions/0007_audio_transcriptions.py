"""Durable private file ASR receipts and job material linkage."""

import sqlalchemy as sa
from alembic import op

revision = "0007_audio_transcriptions"
down_revision = "0006_merge_intake_outreach"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("intake_jobs", sa.Column("audio_transcription_ref", sa.JSON(), nullable=True))
    op.create_table(
        "audio_transcriptions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("audio_hash", sa.String(64), nullable=False),
        sa.Column("audio_format", sa.String(8), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("provider_request_id", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("segments", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("owner_id", "audio_hash", name="uq_owner_audio_hash"),
    )
    for field in ("organization_id", "owner_id", "status"):
        op.create_index("ix_audio_transcriptions_" + field, "audio_transcriptions", [field])


def downgrade():
    op.drop_table("audio_transcriptions")
    with op.batch_alter_table("intake_jobs") as batch:
        batch.drop_column("audio_transcription_ref")
