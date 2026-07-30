from datetime import UTC, datetime

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.database import Base
from app.models import DirectoryEntry, FileEntry
from app.services.dashboard import dashboard_stats, invalidate_dashboard_cache


def test_dashboard_reuses_a_short_lived_snapshot() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    now = datetime.now(UTC)
    db.add_all(
        [
            FileEntry(
                remote_path="/music/track.mp3",
                filename="track.mp3",
                parent_directory="/music",
                extension="mp3",
                size=123,
                first_seen_at=now,
                last_seen_at=now,
                available=True,
                scan_token="scan-1",
            ),
            DirectoryEntry(
                path="/music",
                parent_directory="/",
                first_seen_at=now,
                last_seen_at=now,
                available=True,
                scan_token="scan-1",
            ),
        ]
    )
    db.commit()

    statements: list[str] = []

    def record_statement(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        first = dashboard_stats(db)
        statements_after_first = len(statements)
        second = dashboard_stats(db)
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)
        db.close()

    assert first == second
    assert statements_after_first > 0
    assert len(statements) == statements_after_first


def test_dashboard_snapshot_can_be_invalidated() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)

    assert dashboard_stats(db)["available_files"] == 0

    now = datetime.now(UTC)
    db.add(
        FileEntry(
            remote_path="/music/new.mp3",
            filename="new.mp3",
            parent_directory="/music",
            extension="mp3",
            size=123,
            first_seen_at=now,
            last_seen_at=now,
            available=True,
            scan_token="scan-1",
        )
    )
    db.commit()
    invalidate_dashboard_cache(db)

    assert dashboard_stats(db)["available_files"] == 1
    db.close()
