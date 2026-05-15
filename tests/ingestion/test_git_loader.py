from __future__ import annotations

import os
import subprocess
from contextlib import closing
from pathlib import Path

from src.analytics.database import apply_migrations, connect_database
from src.ingestion.git_loader import ingest_git_repository


def test_ingest_git_repository_persists_history(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    _write(repo / "app.py", "print('hello')\n")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "Add app")
    _write(repo / "app.py", "print('hello')\nprint('bye')\n")
    _write(repo / "README.md", "# Demo\n")
    _git(repo, "add", "app.py", "README.md")
    _git(repo, "commit", "-m", "Update app")

    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        apply_migrations(connection)
        summary = ingest_git_repository(connection, repo)

        counts = {
            table: connection.execute(
                f"SELECT COUNT(*) AS count FROM {table}"
            ).fetchone()["count"]
            for table in ("repositories", "commits", "files", "commit_files")
        }
        run = connection.execute("""
            SELECT run_type, status
            FROM analysis_runs
            ORDER BY id DESC
            LIMIT 1
            """).fetchone()
        app_file = connection.execute("""
            SELECT language, is_deleted
            FROM files
            WHERE path = 'app.py'
            """).fetchone()
        churn = connection.execute("""
            SELECT path, churn, commits_touched
            FROM file_churn
            WHERE path = 'app.py'
            """).fetchone()

    assert summary.commits == 2
    assert summary.files == 2
    assert summary.commit_files == 3
    assert counts == {
        "repositories": 1,
        "commits": 2,
        "files": 2,
        "commit_files": 3,
    }
    assert dict(run) == {"run_type": "git_ingestion", "status": "succeeded"}
    assert dict(app_file) == {"language": "Python", "is_deleted": 0}
    assert dict(churn) == {"path": "app.py", "churn": 2, "commits_touched": 2}


def test_ingest_git_repository_is_idempotent(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    _write(repo / "app.py", "print('hello')\n")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "Add app")

    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        apply_migrations(connection)
        first = ingest_git_repository(connection, repo)
        second = ingest_git_repository(connection, repo)

        counts = {
            table: connection.execute(
                f"SELECT COUNT(*) AS count FROM {table}"
            ).fetchone()["count"]
            for table in ("repositories", "commits", "files", "commit_files")
        }
        runs = connection.execute("""
            SELECT COUNT(*) AS count
            FROM analysis_runs
            WHERE run_type = 'git_ingestion'
              AND status = 'succeeded'
            """).fetchone()["count"]

    assert first == second
    assert counts == {
        "repositories": 1,
        "commits": 1,
        "files": 1,
        "commit_files": 1,
    }
    assert runs == 2


def test_ingest_git_repository_handles_empty_repo(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")

    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        apply_migrations(connection)
        summary = ingest_git_repository(connection, repo)
        counts = {
            table: connection.execute(
                f"SELECT COUNT(*) AS count FROM {table}"
            ).fetchone()["count"]
            for table in ("repositories", "commits", "files", "commit_files")
        }
        run = connection.execute("""
            SELECT status
            FROM analysis_runs
            ORDER BY id DESC
            LIMIT 1
            """).fetchone()

    assert summary.commits == 0
    assert summary.files == 0
    assert summary.commit_files == 0
    assert counts == {
        "repositories": 1,
        "commits": 0,
        "files": 0,
        "commit_files": 0,
    }
    assert run["status"] == "succeeded"


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
