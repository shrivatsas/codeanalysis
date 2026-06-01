"""CLI command for serving the local dashboard."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.analytics.database import DEFAULT_DB_PATH
from src.config import (
    DASHBOARD_HOST_ENV_VAR,
    DASHBOARD_PORT_ENV_VAR,
    DB_PATH_ENV_VAR,
    default_dashboard_host,
    default_dashboard_port,
    default_db_path,
)
from src.dashboards.app import serve_dashboard


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=default_db_path(),
        type=Path,
        help=(
            f"SQLite database path. Defaults to ${DB_PATH_ENV_VAR} "
            f"or {DEFAULT_DB_PATH}."
        ),
    )
    parser.add_argument(
        "--host",
        default=default_dashboard_host(),
        help=(
            "Host interface for the local dashboard. "
            f"Defaults to ${DASHBOARD_HOST_ENV_VAR} or 127.0.0.1."
        ),
    )
    parser.add_argument(
        "--port",
        default=default_dashboard_port(),
        type=int,
        help=(
            "Port for the local dashboard. "
            f"Defaults to ${DASHBOARD_PORT_ENV_VAR} or 8000."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    serve_dashboard(args.db, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
