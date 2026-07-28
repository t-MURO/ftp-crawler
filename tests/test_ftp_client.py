import ftplib
from datetime import UTC

import pytest

from app.services.ftp_client import (
    ResilientFTPClient,
    SessionReusingFTP_TLS,
    is_within_root,
    join_remote_path,
    normalize_remote_path,
    parse_ftp_timestamp,
)
from app.services.settings import CrawlerConfig


def test_normalizes_remote_paths() -> None:
    assert normalize_remote_path("music/../music/file.mp3") == "/music/file.mp3"
    assert normalize_remote_path("/") == "/"


def test_rejects_malformed_remote_names() -> None:
    with pytest.raises(ValueError):
        join_remote_path("/music", "../secret")
    with pytest.raises(ValueError):
        join_remote_path("/music", "nested/file.mp3")


def test_root_boundary_is_enforced() -> None:
    assert is_within_root("/music/house/file.mp3", "/music")
    assert is_within_root("/music", "/music")
    assert not is_within_root("/musical/file.mp3", "/music")


def test_parses_mlsd_timestamp_as_utc() -> None:
    value = parse_ftp_timestamp("20260728153042")
    assert value is not None
    assert value.tzinfo == UTC
    assert value.year == 2026


def test_ftps_data_connection_reuses_control_tls_session(monkeypatch) -> None:
    data_socket = object()
    wrapped_socket = object()

    class ControlSocket:
        session = "control-tls-session"

    class RecordingContext:
        def __init__(self) -> None:
            self.arguments = None

        def wrap_socket(self, socket, **kwargs):
            self.arguments = (socket, kwargs)
            return wrapped_socket

    def fake_ntransfercmd(_self, _command, _rest=None):
        return data_socket, 42

    monkeypatch.setattr(ftplib.FTP, "ntransfercmd", fake_ntransfercmd)
    client = SessionReusingFTP_TLS()
    client.context = RecordingContext()
    client.sock = ControlSocket()
    client.host = "ftp.example.com"
    client._prot_p = True

    connection, size = client.ntransfercmd("MLSD virtual/folder")

    assert connection is wrapped_socket
    assert size == 42
    assert client.context.arguments == (
        data_socket,
        {
            "server_hostname": "ftp.example.com",
            "session": "control-tls-session",
        },
    )


def ftps_config() -> CrawlerConfig:
    return CrawlerConfig(
        ftp_host="ftp.example.com",
        ftp_port=21,
        ftp_protocol="ftps",
        ftp_username="user",
        ftp_password="secret",
        ftp_passive_mode=True,
        ftp_root_path="/",
        ftp_timeout_seconds=10,
        ftp_max_retries=1,
        ftp_request_delay_ms=0,
        ftp_batch_size=100,
        ftp_tls_verify=False,
        music_filename_parsing=False,
    )


def test_virtual_root_listing_uses_relative_command_path() -> None:
    class RecordingFTP:
        listed_path: str | None = None

        def mlsd(self, path, facts):
            self.listed_path = path
            return [
                (
                    "track.mp3",
                    {"type": "file", "size": "123", "modify": "20260728120000"},
                )
            ]

    ftp = RecordingFTP()
    client = ResilientFTPClient(ftps_config())
    client.ftp = ftp

    entries = client.list_directory("/virtual/folder")

    assert ftp.listed_path == "virtual/folder"
    assert entries[0].path == "/virtual/folder/track.mp3"
