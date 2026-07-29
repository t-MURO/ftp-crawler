from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.config import get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    return config


def test_search_upgrade_preserves_catalog_and_resumable_scan(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    try:
        config = alembic_config()
        command.upgrade(config, "0001_initial")
        engine = create_engine(database_url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO scan_runs (
                        id, scan_token, mode, status, source, queued_at
                    ) VALUES (
                        'scan-1', 'token-1', 'full', 'stopped', 'manual',
                        '2026-07-30T12:00:00+00:00'
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO scan_directories (
                        scan_id, path, status, attempts, updated_at
                    ) VALUES (
                        'scan-1', '/music', 'pending', 0,
                        '2026-07-30T12:00:00+00:00'
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO files (
                        remote_path, filename, parent_directory, extension,
                        size, first_seen_at, last_seen_at, available, scan_token
                    ) VALUES (
                        '/music/Deep Anthem.mp3', 'Deep Anthem.mp3', '/music',
                        'mp3', 1234, '2026-07-30T12:00:00+00:00',
                        '2026-07-30T12:00:00+00:00', 1, 'token-1'
                    )
                    """
                )
            )
            connection.execute(
                text("INSERT INTO file_search(file_search) VALUES ('delete-all')")
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM files")) == 1
            assert connection.scalar(text("SELECT count(*) FROM scan_runs")) == 1
            assert connection.scalar(text("SELECT count(*) FROM scan_directories")) == 1
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM file_search "
                        "WHERE file_search MATCH 'anthem'"
                    )
                )
                == 1
            )
            assert (
                connection.scalar(
                    text("SELECT v FROM file_search_config WHERE k = 'automerge'")
                )
                == 2
            )
            assert (
                connection.scalar(
                    text("SELECT v FROM file_search_config WHERE k = 'crisismerge'")
                )
                == 8
            )
            plan = [
                row[3]
                for row in connection.execute(
                    text(
                        "EXPLAIN QUERY PLAN "
                        "SELECT f.id FROM files f WHERE f.available = 1 "
                        "ORDER BY f.filename COLLATE NOCASE ASC, f.id ASC "
                        "LIMIT 50"
                    )
                )
            ]
            assert not any("TEMP B-TREE" in step for step in plan)
    finally:
        get_settings.cache_clear()
