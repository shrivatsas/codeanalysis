from __future__ import annotations

import os
import subprocess
from pathlib import Path

from src.cli.cmd_ingest_git import main


def test_ingest_git_cli_writes_database(tmp_path: Path, capsys) -> None:
    repo = _init_repo(tmp_path / "repo")
    db_path = tmp_path / "codeanalysis.db"
    _write(repo / "app.py", "print('hello')\n")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "Add app")

    exit_code = main(["--repo", str(repo), "--db", str(db_path)])

    assert exit_code == 0
    assert db_path.exists()
    assert "Ingested 1 commits, 1 files, 1 file changes" in capsys.readouterr().out


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
