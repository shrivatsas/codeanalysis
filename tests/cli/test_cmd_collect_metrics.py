from __future__ import annotations

import os
import subprocess
from pathlib import Path

from src.cli.cmd_collect_metrics import main


def test_collect_metrics_cli_writes_database(tmp_path: Path, capsys) -> None:
    repo = _init_repo(tmp_path / "repo")
    db_path = tmp_path / "codeanalysis.db"
    _write(repo / "app.py", "if True:\n    print('hello')\n")

    exit_code = main(["--repo", str(repo), "--db", str(db_path)])

    assert exit_code == 0
    assert db_path.exists()
    assert "Collected 1 files, wrote 1 snapshots" in capsys.readouterr().out


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
