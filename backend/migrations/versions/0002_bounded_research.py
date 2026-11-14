"""Bounded research ledger and explicit executed-stage provenance."""

import sqlalchemy as sa
from alembic import op

revision = "0002_bounded_research"
down_revision = "0001_intake_baseline"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "artifacts",
        sa.Column("source_modes", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column("evidence", sa.Column("public_url", sa.Text(), nullable=True))
    op.add_column("evidence", sa.Column("source_date", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "budgets", sa.Column("search_limit", sa.Integer(), nullable=False, server_default="20")
    )
    op.add_column(
        "budgets", sa.Column("searches_reserved", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "budgets", sa.Column("searches_used", sa.Integer(), nullable=False, server_default="0")
    )
    op.create_table(
        "search_usage",
        sa.Column("task_id", sa.String(64), primary_key=True),
        sa.Column("sequence", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(64), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False, unique=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_search_usage_job_id", "search_usage", ["job_id"])
    _backfill_stage_sources()


def _backfill_stage_sources():
    connection = op.get_bind()
    artifacts = sa.table(
        "artifacts",
        sa.column("artifact_id", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("type", sa.String()),
        sa.column("application_id", sa.String()),
        sa.column("source_mode", sa.String()),
        sa.column("input_refs", sa.JSON()),
        sa.column("source_modes", sa.JSON()),
    )
    applications = sa.table(
        "applications", sa.column("id", sa.String()), sa.column("execution_mode", sa.String())
    )
    modes = dict(
        connection.execute(sa.select(applications.c.id, applications.c.execution_mode)).all()
    )
    rows = connection.execute(sa.select(artifacts)).mappings().all()
    lookup = {(row["artifact_id"], row["version"]): row for row in rows}
    memo = {}

    def resolve(key, visiting):
        empty = {name: None for name in ("candidate_material", "model", "research", "phone")}
        if key in memo:
            return memo[key]
        if key in visiting or len(visiting) >= 100 or key not in lookup:
            return empty
        row = lookup[key]
        sources = []
        for ref in row["input_refs"] or []:
            upstream = (ref.get("artifact_id", ref.get("id")), ref.get("version"))
            if "artifact_id" in ref or ref.get("kind") == "artifact":
                sources.append(resolve(upstream, visiting | {key}))
        for name in empty:
            values = {source[name] for source in sources}
            empty[name] = next(
                (mode for mode in ("mock", "live", "manual") if mode in values), None
            )
        if row["application_id"] in modes:
            empty["candidate_material"] = (
                "mock" if modes[row["application_id"]] == "mock" else "manual"
            )
        if row["type"] in {"D01", "D02", "D03"} and row["source_mode"] in {"live", "mock"}:
            values = {empty["model"], row["source_mode"]}
            empty["model"] = "mock" if "mock" in values else "live"
        # Before this revision research never executed. Do not manufacture a live research source.
        empty["research"], empty["phone"] = None, None
        memo[key] = empty
        return empty

    for key in lookup:
        connection.execute(
            artifacts.update()
            .where(artifacts.c.artifact_id == key[0], artifacts.c.version == key[1])
            .values(source_modes=resolve(key, set()))
        )


def downgrade():
    op.drop_index("ix_search_usage_job_id", table_name="search_usage")
    op.drop_table("search_usage")
    for column in ("searches_used", "searches_reserved", "search_limit"):
        op.drop_column("budgets", column)
    op.drop_column("evidence", "source_date")
    op.drop_column("evidence", "public_url")
    op.drop_column("artifacts", "source_modes")
