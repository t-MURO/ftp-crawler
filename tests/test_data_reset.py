from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import (
    AdminUser,
    AppSetting,
    CrawlLog,
    DirectoryEntry,
    FileEntry,
    ScanDirectory,
    ScanRun,
)
from app.services.data_reset import ActiveScanError, reset_crawl_data


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_crawl_data(db: Session, scan_status: str = "completed") -> None:
    now = datetime.now(UTC)
    scan = ScanRun(
        id="scan-1",
        scan_token="token-1",
        mode="full",
        status=scan_status,
        source="manual",
        queued_at=now,
    )
    db.add_all(
        [
            scan,
            ScanDirectory(
                scan_id=scan.id,
                path="/",
                status="done",
                updated_at=now,
            ),
            CrawlLog(
                scan_id=scan.id,
                created_at=now,
                level="INFO",
                message="Scan complete",
            ),
            DirectoryEntry(
                path="/music",
                parent_directory="/",
                first_seen_at=now,
                last_seen_at=now,
                available=True,
                scan_token=scan.scan_token,
            ),
            FileEntry(
                remote_path="/music/track.mp3",
                filename="track.mp3",
                parent_directory="/music",
                extension="mp3",
                size=123,
                first_seen_at=now,
                last_seen_at=now,
                available=True,
                scan_token=scan.scan_token,
            ),
            AppSetting(key="ftp_root_path", value='"/"'),
            AdminUser(username="admin", password_hash="preserved"),
        ]
    )
    db.commit()


def test_reset_removes_crawl_data_but_preserves_settings_and_admin() -> None:
    db = make_session()
    seed_crawl_data(db)

    deleted = reset_crawl_data(db)

    assert deleted == {
        "scan_directories": 1,
        "crawl_logs": 1,
        "scan_runs": 1,
        "files": 1,
        "directories": 1,
    }
    for model in (ScanDirectory, CrawlLog, ScanRun, FileEntry, DirectoryEntry):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    assert db.scalar(select(func.count()).select_from(AppSetting)) == 1
    assert db.scalar(select(func.count()).select_from(AdminUser)) == 1
    db.close()


def test_reset_is_refused_while_a_scan_is_active() -> None:
    db = make_session()
    seed_crawl_data(db, scan_status="running")

    with pytest.raises(ActiveScanError, match="Stop the active scan"):
        reset_crawl_data(db)

    assert db.scalar(select(func.count()).select_from(FileEntry)) == 1
    assert db.scalar(select(func.count()).select_from(ScanRun)) == 1
    db.close()
