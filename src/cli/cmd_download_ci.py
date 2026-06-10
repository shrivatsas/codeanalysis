"""CLI command for downloading GitHub Actions CI summaries."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.ingestion.github_actions import download_github_actions_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        required=True,
        help="GitHub repository in owner/name form.",
    )
    parser.add_argument(
        "--output",
        default=Path("ci.json"),
        type=Path,
        help="Path to write the downloaded CI summary JSON.",
    )
    parser.add_argument(
        "--run-id",
        type=int,
        help="Download a specific GitHub Actions run ID.",
    )
    parser.add_argument(
        "--branch",
        help="Filter to runs from a specific branch when selecting the latest run.",
    )
    parser.add_argument(
        "--workflow",
        help="Filter to a specific workflow name when selecting the latest run.",
    )
    parser.add_argument(
        "--limit",
        default=20,
        type=int,
        help="Maximum number of recent runs to inspect when choosing the latest run.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = download_github_actions_report(
            args.repo,
            args.output,
            run_id=args.run_id,
            branch=args.branch,
            workflow=args.workflow,
            limit=args.limit,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        "Downloaded "
        f"workflow {summary.workflow_name!r} "
        f"run {summary.run_id} "
        f"to {summary.output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
