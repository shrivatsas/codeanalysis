from __future__ import annotations

import json
import os
import subprocess
from contextlib import closing
from pathlib import Path

import pytest

from src.analytics.database import apply_migrations, connect_database
from src.analytics.static_metrics import collect_static_metrics
from src.ingestion.coverage_loader import ingest_coverage_report
from src.ingestion.git_loader import ingest_git_repository


def test_ingest_coverage_report_writes_latest_coverage_and_risk_gap(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    _write(repo / "app.py", "def add(a, b):\n    return a + b\n")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "Add app")

    coverage_file = tmp_path / "coverage.json"
    coverage_file.write_text(
        json.dumps(
            {
                "measured_at": "2026-05-16T00:00:00Z",
                "files": [
                    {
                        "path": "app.py",
                        "covered_lines": 8,
                        "total_lines": 10,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        apply_migrations(connection)
        ingest_git_repository(connection, repo)
        collect_static_metrics(connection, repo)
        summary = ingest_coverage_report(connection, repo, coverage_file)

        coverage_row = connection.execute(
            """
            SELECT path, covered_lines, total_lines, uncovered_ratio
            FROM latest_coverage_by_file
            WHERE path = 'app.py'
            """
        ).fetchone()
        risk_row = connection.execute(
            """
            SELECT path, coverage_gap, uncovered_ratio
            FROM risk_leaderboard
            WHERE path = 'app.py'
            """
        ).fetchone()
        run = connection.execute(
            """
            SELECT run_type, status
            FROM analysis_runs
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

    assert summary.files == 1
    assert summary.coverage_rows == 1
    assert summary.measured_at == "2026-05-16T00:00:00Z"
    assert coverage_row["path"] == "app.py"
    assert coverage_row["covered_lines"] == 8
    assert coverage_row["total_lines"] == 10
    assert coverage_row["uncovered_ratio"] == pytest.approx(0.2)
    assert risk_row["path"] == "app.py"
    assert risk_row["coverage_gap"] == pytest.approx(0.4)
    assert risk_row["uncovered_ratio"] == pytest.approx(0.2)
    assert dict(run) == {"run_type": "coverage_ingestion", "status": "succeeded"}


def _init_repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init")
    _git(path, "config", "user.name", "Ada Lovelace")
    _git(path, "config", "user.email", "ada@example.com")
    return path


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_DATE": "2026-05-15T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2026-05-15T00:00:00+00:00",
        }
    )
    subprocess.run(
        ("git", *args),
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
