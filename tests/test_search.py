from datetime import UTC, datetime

from sqlalchemy import create_engine, text
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
