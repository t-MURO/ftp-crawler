import pytest
from pydantic import ValidationError

from app.config import Settings
from app.schemas import SettingsUpdate


def test_extension_whitelist_is_normalized() -> None:
    settings = Settings(
        _env_file=None,
        file_extension_whitelist=".MP3, flac,MP3",
    )

    assert settings.file_extension_whitelist == "mp3,flac"
    assert settings.file_extension_whitelist_list == ("mp3", "flac")
    assert (
        SettingsUpdate(file_extension_whitelist=" WAV, .AIF ")
        .file_extension_whitelist
        == "wav,aif"
    )


def test_extension_whitelist_rejects_malformed_values() -> None:
    with pytest.raises(ValidationError, match="Invalid file extension"):
        Settings(_env_file=None, file_extension_whitelist="mp3,../jpg")
