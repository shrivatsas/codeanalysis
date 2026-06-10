"""CLI command for ingesting CI/CD summaries from a local repository."""

from __future__ import annotations

import argparse
from contextlib import closing
from pathlib import Path

from src.analytics.database import DEFAULT_DB_PATH, apply_migrations, connect_database
from src.config import DB_PATH_ENV_VAR, default_db_path
from src.ingestion.ci_loader import ingest_ci_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        required=True,
        type=Path,
        help="Path to the local Git repository to attach CI data to.",
    )
    parser.add_argument(
        "--ci-file",
        required=True,
        type=Path,
        help="Path to a JSON CI/CD summary.",
    )
    parser.add_argument(
        "--db",
        default=default_db_path(),
        type=Path,
        help=(
            f"SQLite database path. Defaults to ${DB_PATH_ENV_VAR} "
            f"or {DEFAULT_DB_PATH}."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    with closing(connect_database(args.db)) as connection:
        apply_migrations(connection)
        summary = ingest_ci_report(connection, args.repo, args.ci_file)

    print(
        "Imported "
        f"{summary.runs} CI runs, "
        f"{summary.jobs} jobs, "
        f"{summary.test_results} test results "
        f"for {summary.repository_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
