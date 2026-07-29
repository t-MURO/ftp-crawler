"""Rebuild FTS and add indexes matching the search sort order.

Revision ID: 0002_search_performance
Revises: 0001_initial
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_search_performance"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_files_available_filename_nocase "
        "ON files (available, filename COLLATE NOCASE, id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_files_available_path_nocase "
        "ON files (available, remote_path COLLATE NOCASE, id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_files_available_modified "
        "ON files (available, modified_at, id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_files_available_first_seen "
        "ON files (available, first_seen_at, id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_files_available_extension_filename "
        "ON files (available, extension COLLATE NOCASE, "
        "filename COLLATE NOCASE, id)"
    )

    # Rebuild from the external-content `files` table. This repairs a stale
    # search index without deleting or rewriting any crawler-owned rows.
    op.execute("INSERT INTO file_search(file_search) VALUES ('rebuild')")
    op.execute("INSERT INTO file_search(file_search) VALUES ('optimize')")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_files_available_extension_filename")
    op.execute("DROP INDEX IF EXISTS ix_files_available_first_seen")
    op.execute("DROP INDEX IF EXISTS ix_files_available_modified")
    op.execute("DROP INDEX IF EXISTS ix_files_available_path_nocase")
    op.execute("DROP INDEX IF EXISTS ix_files_available_filename_nocase")
