"""Create the FTP index, crawler state, and FTS search tables.

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("remote_path", sa.Text(), nullable=False, unique=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("parent_directory", sa.Text(), nullable=False),
        sa.Column("extension", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("modified_at", sa.DateTime(timezone=True)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("scan_token", sa.String(length=36), nullable=False),
        sa.Column("artist", sa.Text()),
        sa.Column("track_title", sa.Text()),
        sa.Column("version", sa.Text()),
        sa.Column("release_year", sa.Integer()),
        sa.Column("label", sa.Text()),
        sa.Column("catalog_number", sa.String(length=128)),
    )
    for index_name, columns in (
        ("ix_files_filename", ["filename"]),
        ("ix_files_parent_directory", ["parent_directory"]),
        ("ix_files_extension", ["extension"]),
        ("ix_files_size", ["size"]),
        ("ix_files_modified_at", ["modified_at"]),
        ("ix_files_first_seen_at", ["first_seen_at"]),
        ("ix_files_available_extension", ["available", "extension"]),
        ("ix_files_available_size", ["available", "size"]),
        ("ix_files_scan_token", ["scan_token"]),
    ):
        op.create_index(index_name, "files", columns)

    op.create_table(
        "directories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("path", sa.Text(), nullable=False, unique=True),
        sa.Column("parent_directory", sa.Text(), nullable=False),
        sa.Column("modified_at", sa.DateTime(timezone=True)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("scan_token", sa.String(length=36), nullable=False),
    )
    op.create_index("ix_directories_parent", "directories", ["parent_directory"])
    op.create_index("ix_directories_available", "directories", ["available"])
    op.create_index("ix_directories_scan_token", "directories", ["scan_token"])

    op.create_table(
        "scan_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("scan_token", sa.String(length=36), nullable=False, unique=True),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("current_directory", sa.Text()),
        sa.Column("directories_queued", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("directories_scanned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_entries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_entries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unchanged_entries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_entries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_entries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.Column("stop_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_scan_runs_status_queued", "scan_runs", ["status", "queued_at"])
    op.create_index("ix_scan_runs_finished", "scan_runs", ["finished_at"])
    op.execute(
        "CREATE UNIQUE INDEX ux_one_running_scan "
        "ON scan_runs ((1)) WHERE status IN ('running', 'stopping')"
    )

    op.create_table(
        "scan_directories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "scan_id",
            sa.String(length=36),
            sa.ForeignKey("scan_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("scan_id", "path", name="uq_scan_directory_path"),
    )
    op.create_index(
        "ix_scan_directories_work",
        "scan_directories",
        ["scan_id", "status", "id"],
    )

    op.create_table(
        "crawl_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "scan_id",
            sa.String(length=36),
            sa.ForeignKey("scan_runs.id", ondelete="SET NULL"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("directory", sa.Text()),
    )
    op.create_index("ix_crawl_logs_created", "crawl_logs", ["created_at"])
    op.create_index("ix_crawl_logs_scan", "crawl_logs", ["scan_id", "id"])
    op.create_index("ix_crawl_logs_level", "crawl_logs", ["level", "id"])

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=128), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.execute(
        """
        CREATE VIRTUAL TABLE file_search USING fts5(
            filename,
            parent_directory,
            remote_path,
            content='files',
            content_rowid='id',
            tokenize='unicode61 remove_diacritics 2'
        )
        """
    )
    op.execute(
        """
        CREATE TRIGGER files_ai AFTER INSERT ON files BEGIN
            INSERT INTO file_search(rowid, filename, parent_directory, remote_path)
            VALUES (new.id, new.filename, new.parent_directory, new.remote_path);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER files_ad AFTER DELETE ON files BEGIN
            INSERT INTO file_search(file_search, rowid, filename, parent_directory, remote_path)
            VALUES ('delete', old.id, old.filename, old.parent_directory, old.remote_path);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER files_au AFTER UPDATE OF filename, parent_directory, remote_path ON files BEGIN
            INSERT INTO file_search(file_search, rowid, filename, parent_directory, remote_path)
            VALUES ('delete', old.id, old.filename, old.parent_directory, old.remote_path);
            INSERT INTO file_search(rowid, filename, parent_directory, remote_path)
            VALUES (new.id, new.filename, new.parent_directory, new.remote_path);
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS files_au")
    op.execute("DROP TRIGGER IF EXISTS files_ad")
    op.execute("DROP TRIGGER IF EXISTS files_ai")
    op.execute("DROP TABLE IF EXISTS file_search")
    op.drop_table("admin_users")
    op.drop_table("app_settings")
    op.drop_table("crawl_logs")
    op.drop_table("scan_directories")
    op.drop_table("scan_runs")
    op.drop_table("directories")
    op.drop_table("files")
