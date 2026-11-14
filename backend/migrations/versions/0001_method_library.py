"""Method document provenance and reviewed method entries."""

import sqlalchemy as sa
from alembic import op

revision = "0001_method_library"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "method_documents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.UniqueConstraint("filename", "sha256"),
    )
    op.create_table(
        "method_entries",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "document_id", sa.String(64), sa.ForeignKey("method_documents.id"), nullable=False
        ),
        sa.Column("paragraph", sa.Integer, nullable=False),
        sa.Column("content", sa.JSON, nullable=False),
        sa.Column("review_status", sa.String(24), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
    )
    op.create_index("ix_method_entries_document_id", "method_entries", ["document_id"])


def downgrade():
    op.drop_table("method_entries")
    op.drop_table("method_documents")
