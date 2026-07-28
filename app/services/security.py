from __future__ import annotations

import hmac
import re
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import AdminUser, utcnow

password_hasher = PasswordHasher()


def seed_admin_user(db: Session, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if not settings.auth_enabled:
        return
    candidate_hash = password_hasher.hash(settings.admin_password)
    db.execute(
        sqlite_insert(AdminUser)
        .values(
            username=settings.admin_username,
            password_hash=candidate_hash,
            updated_at=utcnow(),
        )
        .on_conflict_do_nothing(index_elements=["username"])
    )
    db.commit()
    user = db.scalar(select(AdminUser).where(AdminUser.username == settings.admin_username))
    if user is None:
        return
    try:
        if not password_hasher.verify(user.password_hash, settings.admin_password):
            return
        if password_hasher.check_needs_rehash(user.password_hash):
            user.password_hash = password_hasher.hash(settings.admin_password)
            user.updated_at = utcnow()
            db.commit()
    except (VerifyMismatchError, InvalidHashError):
        user.password_hash = candidate_hash
        user.updated_at = utcnow()
        db.commit()


def verify_login(db: Session, username: str, password: str) -> bool:
    user = db.scalar(select(AdminUser).where(AdminUser.username == username))
    if user is None:
        password_hasher.hash(password or "invalid")
        return False
    try:
        return password_hasher.verify(user.password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def new_csrf_token(request: Request) -> str:
    token = secrets.token_urlsafe(32)
    request.session["csrf_token"] = token
    return token


def get_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        return new_csrf_token(request)
    return str(token)


def require_authenticated(request: Request) -> str:
    settings = get_settings()
    if not settings.auth_enabled:
        return "local"
    username = request.session.get("username")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return str(username)


def require_csrf(request: Request) -> None:
    session_token = str(request.session.get("csrf_token", ""))
    submitted = request.headers.get("X-CSRF-Token", "")
    if not session_token or not submitted or not hmac.compare_digest(session_token, submitted):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token",
        )


def redact_sensitive(message: object, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    result = str(message)
    for secret in (settings.ftp_password, settings.admin_password, settings.session_secret):
        if secret:
            result = result.replace(secret, "[REDACTED]")
    result = re.sub(
        r"(?i)(ftp(?:s)?://[^:/\s]+:)[^@\s]+@",
        r"\1[REDACTED]@",
        result,
    )
    result = re.sub(
        r"(?i)(password|passwd|pwd)(\s*[=:]\s*)\S+",
        r"\1\2[REDACTED]",
        result,
    )
    return result[:4000]
