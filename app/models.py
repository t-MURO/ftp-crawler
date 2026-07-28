from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class FileEntry(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    remote_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    parent_directory: Mapped[str] = mapped_column(Text, nullable=False)
    extension: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    scan_token: Mapped[str] = mapped_column(String(36), nullable=False)
    artist: Mapped[str | None] = mapped_column(Text)
    track_title: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str | None] = mapped_column(Text)
    release_year: Mapped[int | None] = mapped_column(Integer)
    label: Mapped[str | None] = mapped_column(Text)
    catalog_number: Mapped[str | None] = mapped_column(String(128))

    __table_args__ = (
        Index("ix_files_filename", "filename"),
        Index("ix_files_parent_directory", "parent_directory"),
        Index("ix_files_extension", "extension"),
        Index("ix_files_size", "size"),
        Index("ix_files_modified_at", "modified_at"),
        Index("ix_files_first_seen_at", "first_seen_at"),
        Index("ix_files_available_extension", "available", "extension"),
        Index("ix_files_available_size", "available", "size"),
        Index("ix_files_scan_token", "scan_token"),
    )


class DirectoryEntry(Base):
    __tablename__ = "directories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    parent_directory: Mapped[str] = mapped_column(Text, nullable=False)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    scan_token: Mapped[str] = mapped_column(String(36), nullable=False)

    __table_args__ = (
        Index("ix_directories_parent", "parent_directory"),
        Index("ix_directories_available", "available"),
        Index("ix_directories_scan_token", "scan_token"),
    )


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scan_token: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_directory: Mapped[str | None] = mapped_column(Text)
    directories_queued: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    directories_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_entries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_entries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged_entries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_entries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_entries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    stop_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    directories: Mapped[list[ScanDirectory]] = relationship(
        back_populates="scan", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_scan_runs_status_queued", "status", "queued_at"),
        Index("ix_scan_runs_finished", "finished_at"),
    )


class ScanDirectory(Base):
    __tablename__ = "scan_directories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[str] = mapped_column(
        ForeignKey("scan_runs.id", ondelete="CASCADE"), nullable=False
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    scan: Mapped[ScanRun] = relationship(back_populates="directories")

    __table_args__ = (
        UniqueConstraint("scan_id", "path", name="uq_scan_directory_path"),
        Index("ix_scan_directories_work", "scan_id", "status", "id"),
    )


class CrawlLog(Base):
    __tablename__ = "crawl_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[str | None] = mapped_column(
        ForeignKey("scan_runs.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    directory: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_crawl_logs_created", "created_at"),
        Index("ix_crawl_logs_scan", "scan_id", "id"),
        Index("ix_crawl_logs_level", "level", "id"),
    )


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
