from datetime import UTC

import pytest

from app.services.ftp_client import (
    is_within_root,
    join_remote_path,
    normalize_remote_path,
    parse_ftp_timestamp,
)


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
