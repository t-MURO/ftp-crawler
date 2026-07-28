from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _create_engine() -> Engine:
    database_url = get_settings().database_url
    connect_args: dict[str, object] = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        connect_args["timeout"] = 60

    engine = create_engine(
        database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
        future=True,
    )

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=60000")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.close()

    return engine


engine = _create_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
