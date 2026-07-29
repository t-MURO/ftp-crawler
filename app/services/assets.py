from __future__ import annotations

import hashlib
from pathlib import Path


def static_asset_version(static_directory: Path) -> str:
    """Build a short content hash so browsers fetch matching CSS and JavaScript."""
    digest = hashlib.sha256()
    for filename in ("app.js", "styles.css"):
        digest.update(filename.encode())
        digest.update((static_directory / filename).read_bytes())
    return digest.hexdigest()[:12]
