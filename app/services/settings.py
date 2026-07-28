from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

from app.config import Settings, get_settings, normalize_extension_whitelist
from app.models import AppSetting, utcnow

EDITABLE_SETTING_TYPES: dict[str, type] = {
    "ftp_host": str,
    "ftp_port": int,
    "ftp_protocol": str,
    "ftp_username": str,
    "ftp_passive_mode": bool,
    "ftp_root_path": str,
    "file_extension_whitelist": str,
    "ftp_timeout_seconds": int,
    "ftp_max_retries": int,
    "ftp_request_delay_ms": int,
    "scan_schedule": str,
    "default_results_per_page": int,
    "enable_direct_ftp_links": bool,
    "music_filename_parsing": bool,
}


@dataclass(frozen=True)
class CrawlerConfig:
    ftp_host: str
    ftp_port: int
    ftp_protocol: str
    ftp_username: str
    ftp_password: str
    ftp_passive_mode: bool
    ftp_root_path: str
    ftp_timeout_seconds: int
    ftp_max_retries: int
    ftp_request_delay_ms: int
    ftp_batch_size: int
    ftp_tls_verify: bool
    music_filename_parsing: bool
    ftp_excluded_paths: tuple[str, ...] = ()
    file_extension_whitelist: tuple[str, ...] = ()


def _decode_setting(key: str, value: str):
    expected_type = EDITABLE_SETTING_TYPES[key]
    decoded = json.loads(value)
    if expected_type is bool:
        if not isinstance(decoded, bool):
            raise ValueError(f"{key} must be a boolean")
        return decoded
    if expected_type is int:
        if isinstance(decoded, bool):
            raise ValueError(f"{key} must be an integer")
        return int(decoded)
    return str(decoded)


def get_overrides(db: Session) -> dict[str, object]:
    rows = db.query(AppSetting).filter(AppSetting.key.in_(EDITABLE_SETTING_TYPES)).all()
    overrides: dict[str, object] = {}
    for row in rows:
        try:
            overrides[row.key] = _decode_setting(row.key, row.value)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return overrides


def effective_settings(db: Session, base: Settings | None = None) -> dict[str, object]:
    base = base or get_settings()
    result = {key: getattr(base, key) for key in EDITABLE_SETTING_TYPES}
    result.update(get_overrides(db))
    result["ftp_password_configured"] = bool(base.ftp_password)
    return result


def crawler_config(db: Session, base: Settings | None = None) -> CrawlerConfig:
    base = base or get_settings()
    effective = effective_settings(db, base)
    return CrawlerConfig(
        ftp_host=str(effective["ftp_host"]),
        ftp_port=int(effective["ftp_port"]),
        ftp_protocol=str(effective["ftp_protocol"]),
        ftp_username=str(effective["ftp_username"]),
        ftp_password=base.ftp_password,
        ftp_passive_mode=bool(effective["ftp_passive_mode"]),
        ftp_root_path=str(effective["ftp_root_path"]),
        ftp_timeout_seconds=int(effective["ftp_timeout_seconds"]),
        ftp_max_retries=int(effective["ftp_max_retries"]),
        ftp_request_delay_ms=int(effective["ftp_request_delay_ms"]),
        ftp_batch_size=base.ftp_batch_size,
        ftp_tls_verify=base.ftp_tls_verify,
        music_filename_parsing=bool(effective["music_filename_parsing"]),
        ftp_excluded_paths=base.ftp_excluded_paths_list,
        file_extension_whitelist=tuple(
            item
            for item in normalize_extension_whitelist(
                str(effective["file_extension_whitelist"])
            ).split(",")
            if item
        ),
    )


def public_crawler_config(db: Session) -> dict[str, object]:
    config = asdict(crawler_config(db))
    config.pop("ftp_password", None)
    config["file_extension_whitelist"] = ",".join(
        config["file_extension_whitelist"]
    )
    config["ftp_password_configured"] = bool(get_settings().ftp_password)
    return config


def save_overrides(db: Session, values: dict[str, object]) -> dict[str, object]:
    for key, value in values.items():
        if key not in EDITABLE_SETTING_TYPES:
            continue
        row = db.get(AppSetting, key)
        encoded = json.dumps(value)
        if row is None:
            db.add(AppSetting(key=key, value=encoded, updated_at=utcnow()))
        else:
            row.value = encoded
            row.updated_at = utcnow()
    db.commit()
    return effective_settings(db)
