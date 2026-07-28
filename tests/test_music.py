from app.services.music import parse_music_metadata


def test_parses_common_music_filename() -> None:
    result = parse_music_metadata(
        "Artist Name - Track Title (Club Remix) 2024.mp3",
        "/Label Name/CAT123",
    )
    assert result["artist"] == "Artist Name"
    assert result["track_title"] == "Track Title  2024"
    assert result["version"] == "Club Remix"
    assert result["release_year"] == 2024
    assert result["label"] == "CAT123"
    assert result["catalog_number"] == "CAT123"


def test_parser_never_requires_artist_separator() -> None:
    result = parse_music_metadata("A Unicode Tïtle.flac", "/Releases")
    assert result["artist"] is None
    assert result["track_title"] == "A Unicode Tïtle"
