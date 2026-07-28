from __future__ import annotations

import re
from pathlib import PurePosixPath

YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
CATALOG_RE = re.compile(r"\b([A-Z]{2,12}[-_. ]?\d{2,8})\b", re.IGNORECASE)
VERSION_RE = re.compile(
    r"\(([^)]*(?:mix|remix|edit|version|dub|remaster)[^)]*)\)",
    re.IGNORECASE,
)


def parse_music_metadata(filename: str, parent_directory: str) -> dict[str, object | None]:
    stem = PurePosixPath(filename).stem
    cleaned = stem.replace("_", " ").strip()
    parts = re.split(r"\s+-\s+", cleaned, maxsplit=1)
    artist = parts[0].strip() if len(parts) == 2 else None
    title = parts[1].strip() if len(parts) == 2 else cleaned

    version_match = VERSION_RE.search(title)
    version = version_match.group(1).strip() if version_match else None
    if version_match:
        title = (title[: version_match.start()] + title[version_match.end() :]).strip()

    combined = f"{parent_directory}/{cleaned}"
    year_match = YEAR_RE.search(combined)
    catalog_match = CATALOG_RE.search(combined)
    folders = [part for part in PurePosixPath(parent_directory).parts if part != "/"]
    label = folders[-1] if folders else None

    return {
        "artist": artist or None,
        "track_title": title or None,
        "version": version,
        "release_year": int(year_match.group(1)) if year_match else None,
        "label": label,
        "catalog_number": catalog_match.group(1) if catalog_match else None,
    }
