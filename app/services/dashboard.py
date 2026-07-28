from __future__ import annotations

from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session

from app.models import CrawlLog, DirectoryEntry, FileEntry, ScanRun, utcnow


def scan_to_dict(scan: ScanRun | None) -> dict[str, object] | None:
    if scan is None:
        return None
    duration_seconds = None
    if scan.started_at:
        end = scan.finished_at or utcnow()
        started = scan.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=end.tzinfo)
        duration_seconds = max(0, int((end - started).total_seconds()))
    progress = None
    if scan.directories_queued:
        progress = min(100, round(scan.directories_scanned / scan.directories_queued * 100, 1))
    return {
        "id": scan.id,
        "mode": scan.mode,
        "status": scan.status,
        "source": scan.source,
        "queued_at": scan.queued_at.isoformat() if scan.queued_at else None,
        "started_at": scan.started_at.isoformat() if scan.started_at else None,
        "finished_at": scan.finished_at.isoformat() if scan.finished_at else None,
        "duration_seconds": duration_seconds,
        "current_directory": scan.current_directory,
        "directories_queued": scan.directories_queued,
        "directories_scanned": scan.directories_scanned,
        "progress_percent": progress,
        "new": scan.new_entries,
        "updated": scan.updated_entries,
        "unchanged": scan.unchanged_entries,
        "missing": scan.missing_entries,
        "failed": scan.failed_entries,
        "error_message": scan.error_message,
        "stop_requested": scan.stop_requested,
    }


def dashboard_stats(db: Session) -> dict[str, object]:
    totals = db.execute(
        select(
            func.count(FileEntry.id),
            func.coalesce(func.sum(FileEntry.size), 0),
            func.coalesce(
                func.sum(case((FileEntry.available.is_(False), 1), else_=0)),
                0,
            ),
        )
    ).one()
    available_files = db.scalar(
        select(func.count(FileEntry.id)).where(FileEntry.available.is_(True))
    )
    directories = db.scalar(
        select(func.count(DirectoryEntry.id)).where(DirectoryEntry.available.is_(True))
    )
    extensions = db.execute(
        select(
            FileEntry.extension,
            func.count(FileEntry.id).label("count"),
            func.coalesce(func.sum(FileEntry.size), 0).label("size"),
        )
        .where(FileEntry.available.is_(True))
        .group_by(FileEntry.extension)
        .order_by(desc("count"))
        .limit(16)
    ).all()
    current_scan = db.scalar(
        select(ScanRun)
        .where(ScanRun.status.in_(["running", "stopping", "queued"]))
        .order_by(ScanRun.queued_at.desc())
    )
    if current_scan is None:
        current_scan = db.scalar(select(ScanRun).order_by(ScanRun.queued_at.desc()))
    last_success = db.scalar(
        select(ScanRun)
        .where(ScanRun.status == "success")
        .order_by(ScanRun.finished_at.desc())
    )
    recent_errors = db.scalars(
        select(CrawlLog)
        .where(CrawlLog.level == "ERROR")
        .order_by(CrawlLog.id.desc())
        .limit(5)
    ).all()
    return {
        "total_indexed_files": int(totals[0] or 0),
        "available_files": int(available_files or 0),
        "unavailable_files": int(totals[2] or 0),
        "total_directories": int(directories or 0),
        "total_size": int(totals[1] or 0),
        "extensions": [
            {
                "extension": extension or "no extension",
                "count": int(count),
                "size": int(size),
            }
            for extension, count, size in extensions
        ],
        "last_successful_crawl": (
            last_success.finished_at.isoformat()
            if last_success and last_success.finished_at
            else None
        ),
        "scan": scan_to_dict(current_scan),
        "recent_errors": [
            {
                "id": log.id,
                "created_at": log.created_at.isoformat(),
                "message": log.message,
                "directory": log.directory,
            }
            for log in recent_errors
        ],
    }
