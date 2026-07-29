from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import ScanDirectory, ScanRun
from app.services.crawler import continue_scan, save_scan_checkpoint


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_interrupted_scan(db: Session, status: str = "stopped") -> ScanRun:
    now = datetime.now(UTC)
    scan = ScanRun(
        id="scan-1",
        scan_token="token-1",
        mode="full",
        status=status,
        source="manual",
        queued_at=now,
        started_at=now,
        current_directory="/music/current",
        directories_queued=3,
        directories_scanned=1,
        new_entries=42,
    )
    db.add_all(
        [
            scan,
            ScanDirectory(
                scan_id=scan.id,
                path="/music/done",
                status="done",
                updated_at=now,
            ),
            ScanDirectory(
                scan_id=scan.id,
                path="/music/current",
                status="in_progress",
                updated_at=now,
            ),
            ScanDirectory(
                scan_id=scan.id,
                path="/music/next",
                status="pending",
                updated_at=now,
            ),
        ]
    )
    db.commit()
    return scan


def test_checkpoint_returns_current_folder_to_durable_queue() -> None:
    db = make_session()
    scan = seed_interrupted_scan(db)

    checkpoint = save_scan_checkpoint(db, scan)
    db.commit()

    queue = db.scalars(select(ScanDirectory).order_by(ScanDirectory.id)).all()
    assert checkpoint == "/music/current"
    assert scan.current_directory == "/music/current"
    assert [item.status for item in queue] == ["done", "pending", "pending"]
    db.close()


def test_continue_reuses_scan_and_skips_completed_folders() -> None:
    db = make_session()
    original = seed_interrupted_scan(db, status="failed")

    continued = continue_scan(db)

    queue = db.scalars(select(ScanDirectory).order_by(ScanDirectory.id)).all()
    assert continued.id == original.id
    assert continued.scan_token == original.scan_token
    assert continued.status == "queued"
    assert continued.current_directory == "/music/current"
    assert continued.directories_scanned == 1
    assert continued.new_entries == 42
    assert [item.status for item in queue] == ["done", "pending", "pending"]
    db.close()


def test_continue_is_refused_while_another_scan_is_active() -> None:
    db = make_session()
    seed_interrupted_scan(db)
    now = datetime.now(UTC)
    db.add(
        ScanRun(
            id="scan-2",
            scan_token="token-2",
            mode="incremental",
            status="running",
            source="manual",
            queued_at=now,
        )
    )
    db.commit()

    with pytest.raises(RuntimeError, match="already queued or running"):
        continue_scan(db)

    db.close()
