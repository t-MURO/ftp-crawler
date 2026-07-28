from __future__ import annotations

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.models import CrawlLog, DirectoryEntry, FileEntry, ScanDirectory, ScanRun


class ActiveScanError(RuntimeError):
    pass


def reset_crawl_data(db: Session) -> dict[str, int]:
    """Delete crawl/index data while preserving users and application settings."""
    if db.bind is not None and db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))

    active_scan = db.scalar(
        select(ScanRun.id).where(ScanRun.status.in_(["queued", "running", "stopping"]))
    )
    if active_scan is not None:
        db.rollback()
        raise ActiveScanError("Stop the active scan before starting over")

    deleted = {
        "scan_directories": db.execute(delete(ScanDirectory)).rowcount or 0,
        "crawl_logs": db.execute(delete(CrawlLog)).rowcount or 0,
        "scan_runs": db.execute(delete(ScanRun)).rowcount or 0,
        "files": db.execute(delete(FileEntry)).rowcount or 0,
        "directories": db.execute(delete(DirectoryEntry)).rowcount or 0,
    }
    db.commit()
    return deleted
