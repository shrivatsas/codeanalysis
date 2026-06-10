from __future__ import annotations

import json
import os
import subprocess
from contextlib import closing
from pathlib import Path

from src.analytics.database import apply_migrations, connect_database
from src.ingestion.ci_loader import ingest_ci_report


def test_ingest_ci_report_writes_pipeline_job_and_test_rows(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    _write(repo / "app.py", "print('hello')\n")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "Add app")

    ci_file = tmp_path / "ci.json"
    ci_file.write_text(
        json.dumps(
            {
                "pipeline_name": "build",
                "run_key": "run-123",
                "branch": "main",
                "commit_hash": "abc123",
                "status": "failed",
                "started_at": "2026-05-17T10:00:00Z",
                "finished_at": "2026-05-17T10:10:00Z",
                "duration_seconds": 600,
                "jobs": [
                    {
                        "name": "unit",
                        "status": "failed",
                        "started_at": "2026-05-17T10:00:00Z",
                        "finished_at": "2026-05-17T10:08:00Z",
                        "duration_seconds": 480,
                        "failure_reason": "tests failed",
                        "tests": [
                            {
                                "name": "test_add",
                                "status": "failed",
                                "duration_seconds": 2.2,
                                "failure_reason": "assertion",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        apply_migrations(connection)
        summary = ingest_ci_report(connection, repo, ci_file)

        pipeline_run = connection.execute(
            """
            SELECT pipeline_name, run_key, status, duration_seconds
            FROM pipeline_runs
            WHERE pipeline_name = 'build'
            """
        ).fetchone()
        job_run = connection.execute(
            """
            SELECT job_name, status, failure_reason
            FROM job_runs
            """
        ).fetchone()
        test_result = connection.execute(
            """
            SELECT test_name, status, failure_reason
            FROM test_results
            """
        ).fetchone()
        health = connection.execute(
            """
            SELECT pipeline_name, total_runs, failed_runs, failure_rate
            FROM ci_pipeline_health
            WHERE pipeline_name = 'build'
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

    assert summary.runs == 1
    assert summary.jobs == 1
    assert summary.test_results == 1
    assert dict(pipeline_run) == {
        "pipeline_name": "build",
        "run_key": "run-123",
        "status": "failed",
        "duration_seconds": 600.0,
    }
    assert dict(job_run) == {
        "job_name": "unit",
        "status": "failed",
        "failure_reason": "tests failed",
    }
    assert dict(test_result) == {
        "test_name": "test_add",
        "status": "failed",
        "failure_reason": "assertion",
    }
    assert dict(health) == {
        "pipeline_name": "build",
        "total_runs": 1,
        "failed_runs": 1,
        "failure_rate": 1.0,
    }
    assert dict(run) == {"run_type": "ci_ingestion", "status": "succeeded"}


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
