from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from src.cli.cmd_ingest_ci import main


def test_ingest_ci_cli_writes_database(tmp_path: Path, capsys) -> None:
    repo = _init_repo(tmp_path / "repo")
    ci_file = tmp_path / "ci.json"
    _write(repo / "app.py", "print('hello')\n")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "Add app")
    ci_file.write_text(
        json.dumps(
            {
                "pipeline_name": "build",
                "run_key": "run-123",
                "status": "passed",
                "started_at": "2026-05-17T10:00:00Z",
                "jobs": [],
            }
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "codeanalysis.db"

    exit_code = main(
        [
            "--repo",
            str(repo),
            "--ci-file",
            str(ci_file),
            "--db",
            str(db_path),
        ]
    )

    assert exit_code == 0
    assert db_path.exists()
    assert "Imported 1 CI runs, 0 jobs, 0 test results" in capsys.readouterr().out


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
