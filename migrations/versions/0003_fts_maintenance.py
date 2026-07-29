"""Compact the search index and keep future segments merged.

Revision ID: 0003_fts_maintenance
Revises: 0002_search_performance
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_fts_maintenance"
down_revision: str | None = "0002_search_performance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # These FTS5 commands only merge search-index segments. Catalog rows,
    # crawler queues, and scan progress are not rewritten.
    op.execute("INSERT INTO file_search(file_search, rank) VALUES ('automerge', 2)")
    op.execute("INSERT INTO file_search(file_search, rank) VALUES ('crisismerge', 8)")
    op.execute("INSERT INTO file_search(file_search) VALUES ('optimize')")


def downgrade() -> None:
    op.execute("INSERT INTO file_search(file_search, rank) VALUES ('automerge', 4)")
    op.execute("INSERT INTO file_search(file_search, rank) VALUES ('crisismerge', 16)")
