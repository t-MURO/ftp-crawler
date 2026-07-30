from __future__ import annotations

import math
import re
from collections.abc import Mapping
from urllib.parse import quote

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.schemas import SearchParams
from app.services.settings import effective_settings

SORT_COLUMNS = {
    "filename": "f.filename COLLATE NOCASE",
    "path": "f.remote_path COLLATE NOCASE",
    "size": "f.size",
    "modified": "f.modified_at",
    "first_seen": "f.first_seen_at",
}


def build_fts_query(query: str) -> str | None:
    tokens = re.findall(r"[\w]+", query, flags=re.UNICODE)
    if not tokens:
        return None
    return " AND ".join(f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens[:20])


def _serialize_datetime(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _direct_url(
    remote_path: str,
    values: Mapping[str, object],
) -> str | None:
    if not values["enable_direct_ftp_links"]:
        return None
    protocol = str(values["ftp_protocol"])
    host = str(values["ftp_host"])
    port = int(values["ftp_port"])
    username = quote(str(values["ftp_username"]), safe="")
    user_part = f"{username}@" if username else ""
    default_port = 990 if protocol == "ftps" else 21
    port_part = "" if port == default_port else f":{port}"
    path = quote(remote_path, safe="/")
    return f"{protocol}://{user_part}{host}{port_part}{path}"


def search_files(db: Session, params: SearchParams) -> dict[str, object]:
    settings = get_settings()
    per_page = min(params.per_page, settings.max_results_per_page)
    where: list[str] = []
    values: dict[str, object] = {}
    from_clause = "FROM files f"

    fts_query = build_fts_query(params.q)
    if fts_query:
        # SQLite may otherwise drive this join from an `available` index and
        # probe FTS once for every file. CROSS JOIN preserves the written order:
        # match the small FTS result set first, then fetch each file by rowid.
        from_clause = (
            "FROM file_search CROSS JOIN files f "
            "ON f.id = file_search.rowid"
        )
        where.append("file_search MATCH :fts_query")
        values["fts_query"] = fts_query
    elif params.q.strip():
        where.append(
            "(f.filename LIKE :like_query ESCAPE '\\' COLLATE NOCASE "
            "OR f.parent_directory LIKE :like_query ESCAPE '\\' COLLATE NOCASE)"
        )
        escaped = (
            params.q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        values["like_query"] = f"%{escaped}%"

    if params.extension:
        where.append("f.extension = :extension COLLATE NOCASE")
        values["extension"] = params.extension.lower().lstrip(".")
    if params.min_size is not None:
        where.append("f.size >= :min_size")
        values["min_size"] = params.min_size
    if params.max_size is not None:
        where.append("f.size <= :max_size")
        values["max_size"] = params.max_size
    if params.modified_from:
        where.append("f.modified_at >= :modified_from")
        values["modified_from"] = params.modified_from
    if params.modified_to:
        where.append("f.modified_at <= :modified_to")
        values["modified_to"] = params.modified_to
    if params.directory:
        directory = "/" + params.directory.strip().strip("/")
        directory = "/" if directory == "/" else directory
        where.append(
            "(f.parent_directory = :directory OR f.parent_directory LIKE :directory_prefix)"
        )
        values["directory"] = directory
        values["directory_prefix"] = (
            "/%" if directory == "/" else directory.replace("%", "\\%").replace("_", "\\_") + "/%"
        )
    if params.status != "all":
        where.append("f.available = :available")
        values["available"] = params.status == "available"

    where_sql = f" WHERE {' AND '.join(where)}" if where else ""
    sort_column = SORT_COLUMNS[params.sort]
    order = "DESC" if params.order == "desc" else "ASC"
    select_fields = (
        "f.id, f.remote_path, f.filename, f.parent_directory, "
        "f.extension, f.size, f.modified_at, f.first_seen_at, f.last_seen_at, "
        "f.available, f.artist, f.track_title, f.version, f.release_year, "
        "f.label, f.catalog_number"
    )

    if fts_query:
        requested_page = params.page
        offset = (requested_page - 1) * per_page
        rows = db.execute(
            text(
                f"SELECT {select_fields}, COUNT(*) OVER() AS result_total "
                f"{from_clause} {where_sql} "
                f"ORDER BY {sort_column} {order}, f.id ASC "
                "LIMIT :limit OFFSET :offset"
            ),
            {**values, "limit": per_page, "offset": offset},
        ).mappings().all()
        if rows:
            total = int(rows[0]["result_total"])
            pages = max(1, math.ceil(total / per_page))
            page = min(requested_page, pages)
        elif requested_page == 1:
            total = 0
            pages = 1
            page = 1
        else:
            total = db.execute(
                text(f"SELECT COUNT(*) {from_clause} {where_sql}"),
                values,
            ).scalar_one()
            pages = max(1, math.ceil(total / per_page))
            page = min(requested_page, pages)
            rows = db.execute(
                text(
                    f"SELECT {select_fields}, COUNT(*) OVER() AS result_total "
                    f"{from_clause} {where_sql} "
                    f"ORDER BY {sort_column} {order}, f.id ASC "
                    "LIMIT :limit OFFSET :offset"
                ),
                {
                    **values,
                    "limit": per_page,
                    "offset": (page - 1) * per_page,
                },
            ).mappings().all()
    else:
        total = db.execute(
            text(f"SELECT COUNT(*) {from_clause} {where_sql}"),
            values,
        ).scalar_one()
        pages = max(1, math.ceil(total / per_page))
        page = min(params.page, pages)
        rows = db.execute(
            text(
                f"SELECT {select_fields} "
                f"{from_clause} {where_sql} "
                f"ORDER BY {sort_column} {order}, f.id ASC "
                "LIMIT :limit OFFSET :offset"
            ),
            {
                **values,
                "limit": per_page,
                "offset": (page - 1) * per_page,
            },
        ).mappings().all()
    direct_link_settings = effective_settings(db)

    items: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        item.pop("result_total", None)
        for key in ("modified_at", "first_seen_at", "last_seen_at"):
            item[key] = _serialize_datetime(item[key])
        item["direct_url"] = _direct_url(
            str(item["remote_path"]),
            direct_link_settings,
        )
        items.append(item)

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
        "query": params.q,
    }


def get_file_detail(db: Session, file_id: int) -> dict[str, object] | None:
    row = db.execute(
        text(
            "SELECT id, remote_path, filename, parent_directory, extension, size, "
            "modified_at, first_seen_at, last_seen_at, available, artist, "
            "track_title, version, release_year, label, catalog_number "
            "FROM files WHERE id = :file_id"
        ),
        {"file_id": file_id},
    ).mappings().first()
    if not row:
        return None
    item = dict(row)
    for key in ("modified_at", "first_seen_at", "last_seen_at"):
        item[key] = _serialize_datetime(item[key])
    item["direct_url"] = _direct_url(
        str(item["remote_path"]),
        effective_settings(db),
    )
    return item
