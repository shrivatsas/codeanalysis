"""CLI command for serving the local dashboard."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.analytics.database import DEFAULT_DB_PATH
from src.dashboards.app import serve_dashboard


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        type=Path,
        help=f"SQLite database path. Defaults to {DEFAULT_DB_PATH}.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface for the local dashboard.",
    )
    parser.add_argument(
        "--port",
        default=8000,
        type=int,
        help="Port for the local dashboard.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    serve_dashboard(args.db, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
