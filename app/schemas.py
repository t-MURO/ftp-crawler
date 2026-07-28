from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class SearchParams(BaseModel):
    q: str = Field(default="", max_length=500)
    extension: str | None = Field(default=None, max_length=64)
    min_size: int | None = Field(default=None, ge=0)
    max_size: int | None = Field(default=None, ge=0)
    modified_from: datetime | None = None
    modified_to: datetime | None = None
    directory: str | None = Field(default=None, max_length=4096)
    status: Literal["available", "deleted", "all"] = "available"
    sort: Literal[
        "filename",
        "path",
        "size",
        "modified",
        "first_seen",
    ] = "filename"
    order: Literal["asc", "desc"] = "asc"
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=50, ge=10, le=1000)

    @model_validator(mode="after")
    def validate_ranges(self):
        if (
            self.min_size is not None
            and self.max_size is not None
            and self.min_size > self.max_size
        ):
            raise ValueError("Minimum size cannot exceed maximum size")
        if (
            self.modified_from
            and self.modified_to
            and self.modified_from > self.modified_to
        ):
            raise ValueError("Start date cannot exceed end date")
        return self


class ScanCreate(BaseModel):
    mode: Literal["incremental", "full"] = "incremental"


class SettingsUpdate(BaseModel):
    ftp_host: str | None = Field(default=None, min_length=1, max_length=253)
    ftp_port: int | None = Field(default=None, ge=1, le=65535)
    ftp_protocol: Literal["ftp", "ftps"] | None = None
    ftp_username: str | None = Field(default=None, max_length=512)
    ftp_passive_mode: bool | None = None
    ftp_root_path: str | None = Field(default=None, max_length=4096)
    ftp_timeout_seconds: int | None = Field(default=None, ge=5, le=600)
    ftp_max_retries: int | None = Field(default=None, ge=0, le=20)
    ftp_request_delay_ms: int | None = Field(default=None, ge=0, le=60_000)
    scan_schedule: str | None = Field(default=None, max_length=128)
    default_results_per_page: int | None = Field(default=None, ge=10, le=200)
    enable_direct_ftp_links: bool | None = None
    music_filename_parsing: bool | None = None

    @field_validator("ftp_root_path")
    @classmethod
    def validate_root(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if "\x00" in value:
            raise ValueError("FTP root cannot contain a null byte")
        normalized = "/" + value.strip().strip("/")
        return "/" if normalized == "/" else normalized

    @field_validator("scan_schedule")
    @classmethod
    def validate_schedule(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return value
        from croniter import croniter

        if not croniter.is_valid(value.strip()):
            raise ValueError("Invalid cron schedule")
        return value.strip()
