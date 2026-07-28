from __future__ import annotations

import logging
import posixpath
import signal
import threading
import uuid
from datetime import timedelta
from logging.handlers import RotatingFileHandler
from pathlib import PurePosixPath

from croniter import croniter
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import session_scope
from app.models import (
    CrawlLog,
    DirectoryEntry,
    FileEntry,
    ScanDirectory,
    ScanRun,
    utcnow,
)
from app.services.ftp_client import RemoteEntry, ResilientFTPClient, normalize_remote_path
from app.services.music import parse_music_metadata
from app.services.security import redact_sensitive
from app.services.settings import crawler_config, effective_settings

logger = logging.getLogger("port-browser.crawler")


def file_extension(filename: str) -> str:
    suffix = PurePosixPath(filename).suffix
    return suffix[1:].lower() if suffix.startswith(".") else ""


def datetime_changed(left, right) -> bool:
    if left is None or right is None:
        return left != right
    left_value = left.replace(tzinfo=None)
    right_value = right.replace(tzinfo=None)
    return left_value != right_value


def write_crawl_log(
    db: Session,
    scan_id: str | None,
    level: str,
    message: object,
    directory: str | None = None,
    *,
    commit: bool = True,
) -> None:
    safe_message = redact_sensitive(message)
    db.add(
        CrawlLog(
            scan_id=scan_id,
            created_at=utcnow(),
            level=level.upper(),
            message=safe_message,
            directory=directory,
        )
    )
    log_method = (
        level.lower()
        if level.lower() in {"debug", "info", "warning", "error"}
        else "info"
    )
    getattr(logger, log_method)(safe_message)
    if commit:
        db.commit()


def create_scan(db: Session, mode: str, source: str = "manual") -> ScanRun:
    if mode not in {"incremental", "full"}:
        raise ValueError("Scan mode must be incremental or full")
    existing = db.scalar(
        select(ScanRun)
        .where(ScanRun.status.in_(["queued", "running", "stopping"]))
        .order_by(ScanRun.queued_at)
    )
    if existing:
        raise RuntimeError("A scan is already queued or running")

    identifier = str(uuid.uuid4())
    scan = ScanRun(
        id=identifier,
        scan_token=str(uuid.uuid4()),
        mode=mode,
        status="queued",
        source=source,
        queued_at=utcnow(),
    )
    db.add(scan)
    db.commit()
    write_crawl_log(db, scan.id, "INFO", f"{mode.title()} scan queued by {source}.")
    return scan


class CrawlerWorker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.shutdown_event = threading.Event()
        self.next_scheduled_at = None
        self.schedule_expression: str | None = None

    def request_shutdown(self, *_args) -> None:
        self.shutdown_event.set()
        with session_scope() as db:
            scan = db.scalar(
                select(ScanRun).where(ScanRun.status.in_(["running", "stopping"]))
            )
            if scan:
                scan.stop_requested = True
                scan.status = "stopping"

    def recover_interrupted_scans(self) -> None:
        with session_scope() as db:
            interrupted = db.scalars(
                select(ScanRun).where(ScanRun.status.in_(["running", "stopping"]))
            ).all()
            for scan in interrupted:
                db.execute(
                    update(ScanDirectory)
                    .where(
                        ScanDirectory.scan_id == scan.id,
                        ScanDirectory.status == "in_progress",
                    )
                    .values(status="pending")
                )
                scan.status = "queued"
                scan.stop_requested = False
                scan.error_message = "Recovered after worker restart"
                write_crawl_log(
                    db,
                    scan.id,
                    "WARNING",
                    "Worker restarted; the unfinished scan will resume.",
                    commit=False,
                )

    def maybe_schedule_scan(self) -> None:
        with session_scope() as db:
            values = effective_settings(db)
            expression = str(values["scan_schedule"]).strip()
            if not expression:
                self.next_scheduled_at = None
                self.schedule_expression = None
                return
            now = utcnow()
            if expression != self.schedule_expression or self.next_scheduled_at is None:
                try:
                    self.next_scheduled_at = croniter(expression, now).get_next(type(now))
                    self.schedule_expression = expression
                except (KeyError, ValueError) as exc:
                    write_crawl_log(db, None, "ERROR", f"Invalid scan schedule: {exc}")
                    self.next_scheduled_at = now + timedelta(hours=1)
                    self.schedule_expression = expression
                    return
            if now < self.next_scheduled_at:
                return
            try:
                create_scan(db, "incremental", "schedule")
            except RuntimeError:
                pass
            self.next_scheduled_at = croniter(expression, now).get_next(type(now))

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self.request_shutdown)
        signal.signal(signal.SIGINT, self.request_shutdown)
        self.recover_interrupted_scans()
        logger.info("Crawler worker started.")
        while not self.shutdown_event.is_set():
            try:
                self.maybe_schedule_scan()
                with session_scope() as db:
                    scan = db.scalar(
                        select(ScanRun)
                        .where(ScanRun.status == "queued")
                        .order_by(ScanRun.queued_at)
                    )
                    scan_id = scan.id if scan else None
                if scan_id:
                    self.execute_scan(scan_id)
                else:
                    self.shutdown_event.wait(self.settings.worker_poll_seconds)
            except Exception as exc:
                logger.exception("Worker loop error: %s", redact_sensitive(exc))
                self.shutdown_event.wait(min(self.settings.worker_poll_seconds * 2, 10))
        logger.info("Crawler worker stopped.")

    def execute_scan(self, scan_id: str) -> None:
        client: ResilientFTPClient | None = None
        try:
            with session_scope() as db:
                scan = db.get(ScanRun, scan_id)
                if scan is None or scan.status != "queued":
                    return
                config = crawler_config(db)
                root = normalize_remote_path(config.ftp_root_path)
                if not config.ftp_host or not config.ftp_password:
                    raise RuntimeError("FTP connection settings are incomplete")
                scan.status = "running"
                scan.started_at = scan.started_at or utcnow()
                scan.finished_at = None
                scan.stop_requested = False
                existing_queue = db.scalar(
                    select(func.count())
                    .select_from(ScanDirectory)
                    .where(ScanDirectory.scan_id == scan.id)
                )
                if not existing_queue:
                    db.add(
                        ScanDirectory(
                            scan_id=scan.id,
                            path=root,
                            status="pending",
                            updated_at=utcnow(),
                        )
                    )
                    scan.directories_queued = 1
                write_crawl_log(
                    db,
                    scan.id,
                    "INFO",
                    f"Starting {scan.mode} scan at {root}.",
                    root,
                    commit=False,
                )

            def retry_log(message: str) -> None:
                with session_scope() as retry_db:
                    write_crawl_log(retry_db, scan_id, "WARNING", message)

            with session_scope() as db:
                client = ResilientFTPClient(crawler_config(db), retry_log)
            client.connect()

            while not self.shutdown_event.is_set():
                with session_scope() as db:
                    scan = db.get(ScanRun, scan_id)
                    if scan is None:
                        return
                    if scan.stop_requested:
                        self._mark_stopped(db, scan)
                        return
                    work = db.scalar(
                        select(ScanDirectory)
                        .where(
                            ScanDirectory.scan_id == scan_id,
                            ScanDirectory.status.in_(["pending", "error"]),
                        )
                        .order_by(ScanDirectory.id)
                    )
                    if work is None:
                        self._complete_scan(db, scan)
                        return
                    work.status = "in_progress"
                    work.attempts += 1
                    work.updated_at = utcnow()
                    scan.current_directory = work.path
                    path = work.path

                try:
                    entries = client.list_directory(path)
                    if not self._process_directory(scan_id, path, entries):
                        return
                except Exception as exc:
                    with session_scope() as db:
                        scan = db.get(ScanRun, scan_id)
                        work = db.scalar(
                            select(ScanDirectory).where(
                                ScanDirectory.scan_id == scan_id,
                                ScanDirectory.path == path,
                            )
                        )
                        if work:
                            work.status = "done"
                            work.error_message = redact_sensitive(exc)
                            work.updated_at = utcnow()
                        if scan:
                            scan.failed_entries += 1
                            scan.directories_scanned += 1
                        write_crawl_log(
                            db,
                            scan_id,
                            "ERROR",
                            f"Could not scan directory: {exc}",
                            path,
                            commit=False,
                        )
        except Exception as exc:
            with session_scope() as db:
                scan = db.get(ScanRun, scan_id)
                if scan:
                    db.execute(
                        update(ScanDirectory)
                        .where(
                            ScanDirectory.scan_id == scan.id,
                            ScanDirectory.status == "in_progress",
                        )
                        .values(status="pending", updated_at=utcnow())
                    )
                    scan.status = "failed"
                    scan.finished_at = utcnow()
                    scan.error_message = redact_sensitive(exc)
                    scan.current_directory = None
                    write_crawl_log(
                        db,
                        scan_id,
                        "ERROR",
                        f"Scan failed and can be resumed: {exc}",
                        commit=False,
                    )
        finally:
            if client:
                client.close()

    def _process_directory(
        self, scan_id: str, path: str, entries: list[RemoteEntry]
    ) -> bool:
        with session_scope() as db:
            scan = db.get(ScanRun, scan_id)
            if scan is None:
                return False
            config = crawler_config(db)
            now = utcnow()
            directory = db.scalar(
                select(DirectoryEntry).where(DirectoryEntry.path == path)
            )
            parent = posixpath.dirname(path.rstrip("/")) or "/"
            if directory is None:
                db.add(
                    DirectoryEntry(
                        path=path,
                        parent_directory=parent,
                        first_seen_at=now,
                        last_seen_at=now,
                        available=True,
                        scan_token=scan.scan_token,
                    )
                )
            else:
                directory.last_seen_at = now
                directory.available = True
                directory.scan_token = scan.scan_token

        batch_size = max(10, config.ftp_batch_size)
        for start in range(0, len(entries), batch_size):
            batch = entries[start : start + batch_size]
            self._process_batch(scan_id, path, batch, config.music_filename_parsing)
            with session_scope() as db:
                scan = db.get(ScanRun, scan_id)
                if scan and scan.stop_requested:
                    work = db.scalar(
                        select(ScanDirectory).where(
                            ScanDirectory.scan_id == scan_id,
                            ScanDirectory.path == path,
                        )
                    )
                    if work:
                        work.status = "pending"
                    self._mark_stopped(db, scan)
                    return False

        with session_scope() as db:
            scan = db.get(ScanRun, scan_id)
            work = db.scalar(
                select(ScanDirectory).where(
                    ScanDirectory.scan_id == scan_id,
                    ScanDirectory.path == path,
                )
            )
            if scan and work:
                work.status = "done"
                work.error_message = None
                work.updated_at = utcnow()
                scan.directories_scanned += 1
                scan.current_directory = None
        return True

    def _process_batch(
        self,
        scan_id: str,
        parent_path: str,
        entries: list[RemoteEntry],
        parse_music: bool,
    ) -> None:
        with session_scope() as db:
            scan = db.get(ScanRun, scan_id)
            if scan is None:
                return
            now = utcnow()
            directories = [entry for entry in entries if entry.kind == "directory"]
            files = [entry for entry in entries if entry.kind == "file"]

            for entry in directories:
                db.execute(
                    sqlite_insert(ScanDirectory)
                    .values(
                        scan_id=scan_id,
                        path=entry.path,
                        status="pending",
                        attempts=0,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=["scan_id", "path"])
                )
                known = db.scalar(
                    select(DirectoryEntry).where(DirectoryEntry.path == entry.path)
                )
                if known is None:
                    db.add(
                        DirectoryEntry(
                            path=entry.path,
                            parent_directory=parent_path,
                            modified_at=entry.modified_at,
                            first_seen_at=now,
                            last_seen_at=now,
                            available=True,
                            scan_token=scan.scan_token,
                        )
                    )
                else:
                    known.modified_at = entry.modified_at
                    known.last_seen_at = now
                    known.available = True
                    known.scan_token = scan.scan_token

            if directories:
                scan.directories_queued = db.scalar(
                    select(func.count())
                    .select_from(ScanDirectory)
                    .where(ScanDirectory.scan_id == scan_id)
                )

            paths = [entry.path for entry in files]
            existing = {
                item.remote_path: item
                for item in db.scalars(
                    select(FileEntry).where(FileEntry.remote_path.in_(paths))
                ).all()
            }
            for entry in files:
                known = existing.get(entry.path)
                extension = file_extension(entry.name)
                music = (
                    parse_music_metadata(entry.name, parent_path)
                    if parse_music
                    else {
                        "artist": None,
                        "track_title": None,
                        "version": None,
                        "release_year": None,
                        "label": None,
                        "catalog_number": None,
                    }
                )
                if known is None:
                    db.add(
                        FileEntry(
                            remote_path=entry.path,
                            filename=entry.name,
                            parent_directory=parent_path,
                            extension=extension,
                            size=entry.size,
                            modified_at=entry.modified_at,
                            first_seen_at=now,
                            last_seen_at=now,
                            available=True,
                            scan_token=scan.scan_token,
                            **music,
                        )
                    )
                    scan.new_entries += 1
                    continue
                changed = (
                    known.filename != entry.name
                    or known.parent_directory != parent_path
                    or known.extension != extension
                    or known.size != entry.size
                    or datetime_changed(known.modified_at, entry.modified_at)
                    or not known.available
                )
                known.filename = entry.name
                known.parent_directory = parent_path
                known.extension = extension
                known.size = entry.size
                known.modified_at = entry.modified_at
                known.last_seen_at = now
                known.available = True
                known.scan_token = scan.scan_token
                for key, value in music.items():
                    setattr(known, key, value)
                if changed:
                    scan.updated_entries += 1
                else:
                    scan.unchanged_entries += 1

    def _mark_stopped(self, db: Session, scan: ScanRun) -> None:
        db.execute(
            update(ScanDirectory)
            .where(
                ScanDirectory.scan_id == scan.id,
                ScanDirectory.status == "in_progress",
            )
            .values(status="pending", updated_at=utcnow())
        )
        scan.status = "stopped"
        scan.finished_at = utcnow()
        scan.current_directory = None
        scan.stop_requested = False
        write_crawl_log(
            db,
            scan.id,
            "INFO",
            "Scan stopped safely. It can be resumed from the remaining queue.",
            commit=False,
        )

    def _complete_scan(self, db: Session, scan: ScanRun) -> None:
        file_result = db.execute(
            update(FileEntry)
            .where(
                FileEntry.available.is_(True),
                FileEntry.scan_token != scan.scan_token,
            )
            .values(available=False)
        )
        db.execute(
            update(DirectoryEntry)
            .where(
                DirectoryEntry.available.is_(True),
                DirectoryEntry.scan_token != scan.scan_token,
            )
            .values(available=False)
        )
        scan.missing_entries = max(file_result.rowcount or 0, 0)
        scan.status = "success"
        scan.finished_at = utcnow()
        scan.current_directory = None
        write_crawl_log(
            db,
            scan.id,
            "INFO",
            (
                "Scan completed: "
                f"{scan.new_entries} new, {scan.updated_entries} updated, "
                f"{scan.unchanged_entries} unchanged, "
                f"{scan.missing_entries} unavailable."
            ),
            commit=False,
        )
        cutoff = utcnow() - timedelta(days=self.settings.log_retention_days)
        db.execute(delete(CrawlLog).where(CrawlLog.created_at < cutoff))


def main() -> None:
    settings = get_settings()
    settings.log_directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    file_handler = RotatingFileHandler(
        settings.log_directory / "crawler.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logging.getLogger().addHandler(file_handler)
    CrawlerWorker().run()


if __name__ == "__main__":
    main()
