"""Command entry point for analytics validation."""

from contextlib import closing

from src.analytics.database import apply_migrations, connect_database


def main() -> int:
    """Validate that bundled SQLite migrations apply cleanly."""
    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        apply_migrations(connection)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
