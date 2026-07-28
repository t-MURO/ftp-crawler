from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MUSIC_EXTENSIONS = (
    "mp3,flac,wav,aiff,aif,m4a,aac,ogg,oga,opus,wma,ape,dsf,dff"
)


def normalize_extension_whitelist(value: str) -> str:
    normalized: list[str] = []
    for item in value.split(","):
        extension = item.strip().lower().lstrip(".")
        if not extension:
            continue
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", extension):
            raise ValueError(f"Invalid file extension: {item.strip()}")
        normalized.append(extension)
    return ",".join(dict.fromkeys(normalized))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "FTP Indexer"
    app_environment: Literal["development", "production", "test"] = "production"
    web_host: str = "0.0.0.0"
    web_port: int = Field(default=8080, ge=1, le=65535)
    web_workers: int = Field(default=2, ge=1, le=16)
    session_secret: str = "change-me-before-production"
    allowed_hosts: str = "*"

    admin_username: str = "admin"
    admin_password: str = ""
    secure_cookies: bool = False

    ftp_host: str = ""
    ftp_port: int = Field(default=21, ge=1, le=65535)
    ftp_username: str = ""
    ftp_password: str = ""
    ftp_protocol: Literal["ftp", "ftps"] = "ftp"
    ftp_passive_mode: bool = True
    ftp_root_path: str = "/"
    ftp_excluded_paths: str = "/SRV2_BASIC"
    ftp_timeout_seconds: int = Field(default=30, ge=5, le=600)
    ftp_max_retries: int = Field(default=5, ge=0, le=20)
    ftp_request_delay_ms: int = Field(default=250, ge=0, le=60_000)
    ftp_batch_size: int = Field(default=500, ge=10, le=5000)
    ftp_tls_verify: bool = True
    file_extension_whitelist: str = DEFAULT_MUSIC_EXTENSIONS

    database_url: str = "sqlite:////data/ftp-index.db"
    log_directory: Path = Path("/logs")
    config_directory: Path = Path("/config")
    scan_schedule: str = "0 */6 * * *"
    worker_poll_seconds: float = Field(default=2.0, ge=0.25, le=60)

    default_results_per_page: int = Field(default=50, ge=10, le=200)
    max_results_per_page: int = Field(default=200, ge=10, le=1000)
    enable_direct_ftp_links: bool = False
    music_filename_parsing: bool = True
    log_retention_days: int = Field(default=30, ge=1, le=3650)

    @field_validator("ftp_root_path")
    @classmethod
    def validate_root_path(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("FTP root path cannot contain null bytes")
        value = "/" + value.strip().strip("/")
        return "/" if value == "/" else value

    @field_validator("ftp_excluded_paths")
    @classmethod
    def validate_excluded_paths(cls, value: str) -> str:
        normalized: list[str] = []
        for item in value.split(","):
            item = item.strip()
            if not item:
                continue
            if "\x00" in item:
                raise ValueError("Excluded FTP paths cannot contain null bytes")
            path = "/" + item.strip("/")
            if path == "/":
                raise ValueError("The FTP root cannot be excluded")
            normalized.append(path)
        return ",".join(dict.fromkeys(normalized))

    @field_validator("file_extension_whitelist")
    @classmethod
    def validate_extension_whitelist(cls, value: str) -> str:
        return normalize_extension_whitelist(value)

    @property
    def ftp_excluded_paths_list(self) -> tuple[str, ...]:
        return tuple(
            item for item in self.ftp_excluded_paths.split(",") if item
        )

    @property
    def file_extension_whitelist_list(self) -> tuple[str, ...]:
        return tuple(
            item for item in self.file_extension_whitelist.split(",") if item
        )

    @property
    def auth_enabled(self) -> bool:
        return bool(self.admin_password)

    @property
    def allowed_hosts_list(self) -> list[str]:
        return [part.strip() for part in self.allowed_hosts.split(",") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
