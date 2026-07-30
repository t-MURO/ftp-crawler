from datetime import UTC, datetime

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from app.database import Base
from app.models import FileEntry
from app.schemas import SearchParams
from app.services.search import build_fts_query, search_files


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE VIRTUAL TABLE file_search USING fts5(
                    filename,
                    parent_directory,
                    remote_path,
                    content='files',
                    content_rowid='id',
                    tokenize='unicode61 remove_diacritics 2'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TRIGGER files_ai AFTER INSERT ON files BEGIN
                    INSERT INTO file_search(rowid, filename, parent_directory, remote_path)
                    VALUES (new.id, new.filename, new.parent_directory, new.remote_path);
                END
                """
            )
        )
    return Session(engine)


def test_fts_query_uses_safe_prefix_tokens() -> None:
    assert build_fts_query('deep "house"') == '"deep"* AND "house"*'
    assert build_fts_query("!!!") is None


def test_search_is_case_insensitive_and_prefix_based() -> None:
    db = make_session()
    now = datetime.now(UTC)
    db.add_all(
        [
            FileEntry(
                remote_path="/House/Deep Anthem.mp3",
                filename="Deep Anthem.mp3",
                parent_directory="/House",
                extension="mp3",
                size=1234,
                first_seen_at=now,
                last_seen_at=now,
                available=True,
                scan_token="scan-1",
            ),
            FileEntry(
                remote_path="/Techno/Other.wav",
                filename="Other.wav",
                parent_directory="/Techno",
                extension="wav",
                size=5678,
                first_seen_at=now,
                last_seen_at=now,
                available=True,
                scan_token="scan-1",
            ),
        ]
    )
    db.commit()

    result = search_files(db, SearchParams(q="deep ant", per_page=10))
    assert result["total"] == 1
    assert result["items"][0]["filename"] == "Deep Anthem.mp3"

    filtered = search_files(db, SearchParams(extension="wav", per_page=10))
    assert filtered["total"] == 1
    assert filtered["items"][0]["filename"] == "Other.wav"
    db.close()


def test_search_loads_link_settings_once_per_page() -> None:
    db = make_session()
    now = datetime.now(UTC)
    db.add_all(
        [
            FileEntry(
                remote_path=f"/music/track-{index}.mp3",
                filename=f"Track {index}.mp3",
                parent_directory="/music",
                extension="mp3",
                size=index,
                first_seen_at=now,
                last_seen_at=now,
                available=True,
                scan_token="scan-1",
            )
            for index in range(60)
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

    event.listen(db.bind, "before_cursor_execute", record_statement)
    try:
        result = search_files(db, SearchParams(per_page=50))
    finally:
        event.remove(db.bind, "before_cursor_execute", record_statement)

    assert len(result["items"]) == 50
    assert len(statements) == 3
    assert sum("app_settings" in statement for statement in statements) == 1
    db.close()


def test_fts_search_gets_count_and_page_in_one_search_query() -> None:
    db = make_session()
    now = datetime.now(UTC)
    db.add_all(
        [
            FileEntry(
                remote_path=f"/music/Anetha Track {index}.mp3",
                filename=f"Anetha Track {index}.mp3",
                parent_directory="/music",
                extension="mp3",
                size=index,
                first_seen_at=now,
                last_seen_at=now,
                available=True,
                scan_token="scan-1",
            )
            for index in range(12)
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

    event.listen(db.bind, "before_cursor_execute", record_statement)
    try:
        result = search_files(db, SearchParams(q="anetha", per_page=10))
    finally:
        event.remove(db.bind, "before_cursor_execute", record_statement)

    search_statements = [statement for statement in statements if "file_search" in statement]
    assert result["total"] == 12
    assert len(result["items"]) == 10
    assert len(search_statements) == 1
    assert "COUNT(*) OVER()" in search_statements[0]
    assert "FROM file_search CROSS JOIN files f" in search_statements[0]
    db.close()
