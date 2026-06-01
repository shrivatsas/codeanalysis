"""CLI command for ingesting coverage artifacts from a local repository."""

from __future__ import annotations

import argparse
from contextlib import closing
from pathlib import Path

from src.analytics.database import DEFAULT_DB_PATH, apply_migrations, connect_database
from src.ingestion.coverage_loader import ingest_coverage_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        required=True,
        type=Path,
        help="Path to the local Git repository to attach coverage to.",
    )
    parser.add_argument(
        "--coverage-file",
        required=True,
        type=Path,
        help="Path to a JSON coverage artifact.",
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
        summary = ingest_coverage_report(connection, args.repo, args.coverage_file)

    print(
        "Imported "
        f"{summary.coverage_rows} coverage rows "
        f"for {summary.files} files "
        f"from {summary.coverage_rows} coverage artifact entries "
        f"at {summary.measured_at} "
        f"for {summary.repository_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
