from __future__ import annotations

import ftplib
import posixpath
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeVar

from app.services.security import redact_sensitive
from app.services.settings import CrawlerConfig

T = TypeVar("T")


@dataclass(frozen=True)
class RemoteEntry:
    name: str
    path: str
    kind: str
    size: int
    modified_at: datetime | None


def normalize_remote_path(path: str) -> str:
    if "\x00" in path:
        raise ValueError("Remote path contains a null byte")
    normalized = posixpath.normpath("/" + path.lstrip("/"))
    return "/" if normalized == "." else normalized


def join_remote_path(parent: str, name: str) -> str:
    if not name or name in {".", ".."}:
        raise ValueError("Invalid remote filename")
    if "\x00" in name or "/" in name:
        raise ValueError("Remote filename contains a forbidden path separator")
    return normalize_remote_path(posixpath.join(normalize_remote_path(parent), name))


def is_within_root(path: str, root: str) -> bool:
    path = normalize_remote_path(path)
    root = normalize_remote_path(root)
    return root == "/" or path == root or path.startswith(root + "/")


def parse_ftp_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y%m%d%H%M%S.%f", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


class SessionReusingFTP_TLS(ftplib.FTP_TLS):
    """Explicit FTPS client that reuses the control TLS session for data sockets."""

    def ntransfercmd(self, cmd: str, rest: str | None = None):
        connection, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if not self._prot_p:
            return connection, size

        wrap_options: dict[str, object] = {"server_hostname": self.host}
        session = getattr(self.sock, "session", None)
        if session is not None:
            wrap_options["session"] = session
        connection = self.context.wrap_socket(connection, **wrap_options)
        return connection, size


class ResilientFTPClient:
    def __init__(
        self,
        config: CrawlerConfig,
        on_retry: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.on_retry = on_retry
        self.ftp: ftplib.FTP | ftplib.FTP_TLS | None = None

    def connect(self) -> None:
        self.close()
        if not self.config.ftp_host:
            raise RuntimeError("FTP_HOST is not configured")
        if not self.config.ftp_password:
            raise RuntimeError("FTP_PASSWORD is not configured")

        if self.config.ftp_protocol == "ftps":
            context = (
                ssl.create_default_context()
                if self.config.ftp_tls_verify
                else ssl._create_unverified_context()
            )
            ftp: ftplib.FTP | ftplib.FTP_TLS = SessionReusingFTP_TLS(
                timeout=self.config.ftp_timeout_seconds,
                context=context,
                encoding="utf-8",
            )
        else:
            ftp = ftplib.FTP(timeout=self.config.ftp_timeout_seconds, encoding="utf-8")

        ftp.connect(
            host=self.config.ftp_host,
            port=self.config.ftp_port,
            timeout=self.config.ftp_timeout_seconds,
        )
        ftp.login(self.config.ftp_username, self.config.ftp_password)
        if isinstance(ftp, ftplib.FTP_TLS):
            ftp.prot_p()
        ftp.set_pasv(self.config.ftp_passive_mode)
        try:
            ftp.sendcmd("OPTS UTF8 ON")
        except ftplib.all_errors:
            pass
        self.ftp = ftp

    def close(self) -> None:
        if self.ftp is None:
            return
        try:
            self.ftp.quit()
        except ftplib.all_errors:
            try:
                self.ftp.close()
            except ftplib.all_errors:
                pass
        finally:
            self.ftp = None

    def _run_with_retry(self, operation: Callable[[ftplib.FTP], T]) -> T:
        last_error: Exception | None = None
        for attempt in range(self.config.ftp_max_retries + 1):
            try:
                if self.ftp is None:
                    self.connect()
                assert self.ftp is not None
                result = operation(self.ftp)
                if self.config.ftp_request_delay_ms:
                    time.sleep(self.config.ftp_request_delay_ms / 1000)
                return result
            except ftplib.all_errors as exc:
                last_error = exc
                self.close()
                if attempt >= self.config.ftp_max_retries:
                    break
                delay = min(2**attempt, 30)
                if self.on_retry:
                    self.on_retry(
                        redact_sensitive(
                            f"FTP request failed; reconnecting in {delay}s "
                            f"(attempt {attempt + 1}/{self.config.ftp_max_retries}): {exc}"
                        )
                    )
                time.sleep(delay)
        raise RuntimeError(redact_sensitive(f"FTP request failed after retries: {last_error}"))

    def list_directory(self, path: str) -> list[RemoteEntry]:
        path = normalize_remote_path(path)
        if not is_within_root(path, self.config.ftp_root_path):
            raise ValueError("Refusing to scan outside the configured FTP root")
        command_path = path if path == "/" else path.lstrip("/")

        def operation(ftp: ftplib.FTP) -> list[RemoteEntry]:
            entries: list[RemoteEntry] = []
            for name, facts in ftp.mlsd(
                command_path,
                facts=["type", "size", "modify"],
            ):
                if not name or name in {".", ".."}:
                    continue
                remote_path = join_remote_path(path, name)
                kind = str(facts.get("type", "")).lower()
                if kind in {"cdir", "pdir"}:
                    continue
                size_text = str(facts.get("size", "0"))
                size = int(size_text) if size_text.isdigit() else 0
                entries.append(
                    RemoteEntry(
                        name=name,
                        path=remote_path,
                        kind="directory" if kind == "dir" else "file",
                        size=size,
                        modified_at=parse_ftp_timestamp(facts.get("modify")),
                    )
                )
            return entries

        return self._run_with_retry(operation)
