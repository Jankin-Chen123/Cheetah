"""Independent talent intake and many-to-many occupational routing."""

import sqlalchemy as sa
from alembic import op

revision = "0004_talent_routing"
down_revision = "0003_pi_research"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("tasks") as batch:
        batch.alter_column("job_id", existing_type=sa.String(64), nullable=True)
    op.add_column(
        "intake_jobs",
        sa.Column("routing_directions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column("applications", sa.Column("talent_id", sa.String(64), nullable=True))
    op.create_index("ix_applications_talent_id", "applications", ["talent_id"])
    op.add_column(
        "applications",
        sa.Column("routing", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_table(
        "talents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("material_text", sa.Text(), nullable=False),
        sa.Column("material_hash", sa.String(64), nullable=False),
        sa.Column("execution_mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "owner_id", "material_hash", "execution_mode", name="uq_talent_material"
        ),
    )
    for field in ("organization_id", "owner_id"):
        op.create_index("ix_talents_" + field, "talents", [field])
    op.create_table(
        "talent_profiles",
        sa.Column("talent_id", sa.String(64), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("directions", sa.JSON(), nullable=False),
        sa.Column("classification_source", sa.String(16), nullable=False),
        sa.Column("classification_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    # Jobless tasks cannot be represented by the old schema. Refuse rather than delete data.
    if op.get_bind().execute(sa.text("SELECT count(*) FROM talents")).scalar():
        raise RuntimeError("Talent records exist; preserve them before downgrading this migration")
    if op.get_bind().execute(sa.text("SELECT count(*) FROM tasks WHERE job_id IS NULL")).scalar():
        raise RuntimeError("Talent tasks exist; archive them before downgrading this migration")
    op.drop_table("talent_profiles")
    op.drop_table("talents")
    op.drop_index("ix_applications_talent_id", table_name="applications")
    with op.batch_alter_table("applications") as batch:
        batch.drop_column("routing")
        batch.drop_column("talent_id")
    with op.batch_alter_table("intake_jobs") as batch:
        batch.drop_column("routing_directions")
    with op.batch_alter_table("tasks") as batch:
        batch.alter_column("job_id", existing_type=sa.String(64), nullable=False)
