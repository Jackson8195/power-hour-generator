"""Small, idempotent schema migrations for existing SQLite databases.

``Base.metadata.create_all`` only creates missing tables; it never alters existing ones.
When a model changes shape in a way SQLAlchemy can't apply with ADD COLUMN (e.g. dropping
a UNIQUE constraint), the table is rebuilt here, preserving its rows.
"""

import logging

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.database import Base

logger = logging.getLogger(__name__)

CHANGEOVER_TABLE = "changover_clips"


def migrate_changeover_table(conn: Connection) -> None:
    """Allow several changeover clips per project (drops UNIQUE(project_id), adds columns).

    Old tables have no ``origin`` column. Existing rows are the single user-configured
    changeover, so they carry over as ``origin='manual'`` at position 0.
    """
    columns = {row[1] for row in conn.execute(text(f"PRAGMA table_info({CHANGEOVER_TABLE})"))}
    if not columns or "origin" in columns:
        return  # no table yet (create_all will build it) or already migrated

    legacy = f"{CHANGEOVER_TABLE}_legacy"
    logger.info("Migrating %s to support multiple changeover clips per project", CHANGEOVER_TABLE)
    conn.execute(text(f"DROP TABLE IF EXISTS {legacy}"))
    conn.execute(text(f"ALTER TABLE {CHANGEOVER_TABLE} RENAME TO {legacy}"))
    Base.metadata.tables[CHANGEOVER_TABLE].create(conn)

    carried = [
        c for c in (
            "id", "project_id", "source_type", "youtube_id", "image_path", "audio_path",
            "raw_video_path", "output_path", "duration", "trim_start", "trim_end",
            "status", "error_message", "created_at", "updated_at",
        )
        if c in columns
    ]
    cols = ", ".join(carried)
    conn.execute(text(
        f"INSERT INTO {CHANGEOVER_TABLE} ({cols}, origin, position, label) "
        f"SELECT {cols}, 'manual', 0, '' FROM {legacy}"
    ))
    conn.execute(text(f"DROP TABLE {legacy}"))


# Columns added to existing tables after release: (table, column, SQL type + default).
ADDED_COLUMNS = [
    (CHANGEOVER_TABLE, "style", "TEXT DEFAULT ''"),
]


def add_missing_columns(conn: Connection) -> None:
    """ADD COLUMN for new nullable columns on tables that already exist (idempotent)."""
    for table, column, ddl in ADDED_COLUMNS:
        columns = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
        if columns and column not in columns:
            logger.info("Adding column %s.%s", table, column)
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
