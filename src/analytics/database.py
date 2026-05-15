"""SQLite connection and migration helpers."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterable
from pathlib import Path

DEFAULT_DB_PATH = Path("data/codeanalysis.db")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MIGRATIONS_DIR = PROJECT_ROOT / "schema"


def connect_database(
    path: str | Path = DEFAULT_DB_PATH,
    *,
    enable_wal: bool = True,
) -> sqlite3.Connection:
    """Open a configured SQLite connection."""
    db_path = Path(path)
    if db_path != Path(":memory:"):
        db_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")

    if enable_wal and db_path != Path(":memory:"):
        connection.execute("PRAGMA journal_mode = WAL")

    return connection


def apply_migrations(
    connection: sqlite3.Connection,
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
) -> list[str]:
    """Apply pending SQL migrations and return applied migration names."""
    ensure_migration_table(connection)
    applied = _applied_migrations(connection)
    applied_now: list[str] = []

    for migration_path in _migration_files(Path(migrations_dir)):
        sql = migration_path.read_text(encoding="utf-8")
        checksum = _checksum(sql)
        applied_checksum = applied.get(migration_path.name)

        if applied_checksum is not None:
            if applied_checksum != checksum:
                raise ValueError(
                    f"Migration {migration_path.name} has changed since it was applied"
                )
            continue

        with connection:
            connection.executescript(sql)
            connection.execute(
                """
                INSERT INTO schema_migrations (name, checksum)
                VALUES (?, ?)
                """,
                (migration_path.name, checksum),
            )
        applied_now.append(migration_path.name)

    return applied_now


def ensure_migration_table(connection: sqlite3.Connection) -> None:
    """Create the migration bookkeeping table if needed."""
    connection.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
          name TEXT PRIMARY KEY,
          checksum TEXT NOT NULL,
          applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """)
    connection.commit()


def _applied_migrations(connection: sqlite3.Connection) -> dict[str, str]:
    rows = connection.execute("SELECT name, checksum FROM schema_migrations").fetchall()
    return {row["name"]: row["checksum"] for row in rows}


def _migration_files(migrations_dir: Path) -> Iterable[Path]:
    if not migrations_dir.exists():
        raise FileNotFoundError(
            f"Migrations directory does not exist: {migrations_dir}"
        )
    return sorted(
        path
        for path in migrations_dir.iterdir()
        if path.is_file() and path.suffix == ".sql"
    )


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()
