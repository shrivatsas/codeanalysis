"""CLI command for collecting static file metrics from a local Git repository."""

from __future__ import annotations

import argparse
from contextlib import closing
from pathlib import Path

from src.analytics.database import DEFAULT_DB_PATH, apply_migrations, connect_database
from src.analytics.static_metrics import collect_static_metrics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        required=True,
        type=Path,
        help="Path to the local Git repository to scan.",
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        type=Path,
        help=f"SQLite database path. Defaults to {DEFAULT_DB_PATH}.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    with closing(connect_database(args.db)) as connection:
        apply_migrations(connection)
        summary = collect_static_metrics(connection, args.repo)

    print(
        "Collected "
        f"{summary.files} files, "
        f"wrote {summary.snapshots} snapshots, "
        f"marked {summary.deleted_files} deleted "
        f"from {summary.repository_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
