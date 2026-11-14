from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from app.core.database import Base


def test_research_migration_preserves_existing_mock_lineage_without_inventing_research(
    api, runtime
):
    from conftest import drain, post, published_job
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.core.models import Artifact

    job_id, _ = published_job(api, runtime)
    post(
        api,
        f"/jobs/{job_id}/resume-batches",
        {
            "execution_mode": "mock",
            "items": [{"client_item_id": "one", "name": "虚构.txt", "text": "工作年限：5"}],
        },
        expected=202,
    )
    drain(runtime)
    with Session(runtime[1]) as db:
        before = {
            (item.artifact_id, item.version): (item.content, item.source_modes)
            for item in db.scalars(select(Artifact))
        }
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with runtime[1].begin() as connection:
        config.attributes["connection"] = connection
        command.stamp(config, "head")
        command.downgrade(config, "0001_intake_baseline")
        command.upgrade(config, "head")
    with Session(runtime[1]) as db:
        for item in db.scalars(select(Artifact)):
            original_content, original_modes = before[item.artifact_id, item.version]
            assert item.content == original_content
            assert item.source_modes == original_modes
            assert item.source_modes["research"] is None and item.source_modes["phone"] is None


def test_alembic_upgrade_matches_models_and_downgrade_roundtrip(runtime):
    engine = runtime[1]
    # Isolated fixture database/schema only; the application never calls create_all/drop_all.
    Base.metadata.drop_all(engine)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        assert set(Base.metadata.tables) <= set(inspect(connection).get_table_names())
        command.downgrade(config, "base")
        assert not (set(Base.metadata.tables) & set(inspect(connection).get_table_names()))
        command.upgrade(config, "head")
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
