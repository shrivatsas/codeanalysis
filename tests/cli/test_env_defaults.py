from __future__ import annotations

from pathlib import Path

from src.cli.cmd_collect_metrics import build_parser as build_collect_parser
from src.cli.cmd_ingest_ci import build_parser as build_ci_parser
from src.cli.cmd_ingest_coverage import build_parser as build_coverage_parser
from src.cli.cmd_ingest_git import build_parser as build_git_parser
from src.cli.cmd_serve_dashboard import build_parser as build_dashboard_parser


def test_cli_defaults_follow_environment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "codeanalysis.db"
    monkeypatch.setenv("CODEANALYSIS_DB_PATH", str(db_path))
    monkeypatch.setenv("CODEANALYSIS_DASHBOARD_HOST", "0.0.0.0")
    monkeypatch.setenv("CODEANALYSIS_DASHBOARD_PORT", "9090")

    git_args = build_git_parser().parse_args(["--repo", "/tmp/repo"])
    collect_args = build_collect_parser().parse_args(["--repo", "/tmp/repo"])
    ci_args = build_ci_parser().parse_args(
        ["--repo", "/tmp/repo", "--ci-file", "/tmp/ci.json"]
    )
    coverage_args = build_coverage_parser().parse_args(
        ["--repo", "/tmp/repo", "--coverage-file", "/tmp/coverage.json"]
    )
    dashboard_args = build_dashboard_parser().parse_args([])

    assert git_args.db == db_path
    assert collect_args.db == db_path
    assert ci_args.db == db_path
    assert coverage_args.db == db_path
    assert dashboard_args.db == db_path
    assert dashboard_args.host == "0.0.0.0"
    assert dashboard_args.port == 9090
