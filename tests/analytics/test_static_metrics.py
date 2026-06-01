from __future__ import annotations

import os
import subprocess
from contextlib import closing
from pathlib import Path

from src.analytics.database import apply_migrations, connect_database
from src.analytics.static_metrics import collect_static_metrics


def test_collect_static_metrics_persists_snapshots(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    _write(
        repo / "app.py",
        "def add(a, b):\n    if a > b:\n        return a\n    return b\n",
    )
    _write(repo / "README.md", "# Demo\n\nOne line.\n")

    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        apply_migrations(connection)
        summary = collect_static_metrics(connection, repo)

        app_file = connection.execute(
            """
            SELECT language, is_deleted, current_size_bytes
            FROM files
            WHERE path = 'app.py'
            """
        ).fetchone()
        app_snapshot = connection.execute(
            """
            SELECT loc, complexity
            FROM latest_file_metrics
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

    assert summary.files == 2
    assert summary.snapshots == 2
    assert summary.deleted_files == 0
    assert dict(app_file) == {
        "language": "Python",
        "is_deleted": 0,
        "current_size_bytes": len(
            b"def add(a, b):\n    if a > b:\n        return a\n    return b\n"
        ),
    }
    assert dict(app_snapshot) == {"loc": 4, "complexity": 2.0}
    assert dict(run) == {"run_type": "static_metrics", "status": "succeeded"}


def test_collect_static_metrics_marks_deleted_files(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    _write(repo / "app.py", "print('hello')\n")

    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        apply_migrations(connection)
        first = collect_static_metrics(connection, repo)

        (repo / "app.py").unlink()
        second = collect_static_metrics(connection, repo)

        app_file = connection.execute(
            """
            SELECT language, is_deleted, current_size_bytes
            FROM files
            WHERE path = 'app.py'
            """
        ).fetchone()
        snapshots = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM metrics_snapshot
            WHERE file_id = (
              SELECT id
              FROM files
              WHERE path = 'app.py'
            )
            """
        ).fetchone()["count"]
        latest = connection.execute(
            """
            SELECT loc, complexity
            FROM latest_file_metrics
            WHERE path = 'app.py'
            """
        ).fetchone()

    assert first.files == 1
    assert first.snapshots == 1
    assert second.files == 1
    assert second.snapshots == 1
    assert dict(app_file) == {
        "language": "Python",
        "is_deleted": 1,
        "current_size_bytes": None,
    }
    assert snapshots == 2
    assert dict(latest) == {"loc": None, "complexity": None}


def test_collect_static_metrics_skips_directory_paths(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    (repo / "docs").mkdir()

    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        apply_migrations(connection)
        repository_id = connection.execute(
            """
            INSERT INTO repositories (name, path, default_branch)
            VALUES ('repo', ?, 'main')
            RETURNING id
            """,
            (str(repo),),
        ).fetchone()["id"]
        connection.execute(
            """
            INSERT INTO files (
              repository_id,
              path,
              language,
              current_size_bytes,
              is_deleted
            )
            VALUES (?, 'docs', NULL, NULL, 0)
            """,
            (repository_id,),
        )

        summary = collect_static_metrics(connection, repo)
        file_row = connection.execute(
            """
            SELECT is_deleted, current_size_bytes
            FROM files
            WHERE path = 'docs'
            """,
        ).fetchone()
        snapshot_row = connection.execute(
            """
            SELECT loc, complexity
            FROM latest_file_metrics
            WHERE path = 'docs'
            """,
        ).fetchone()

    assert summary.files == 1
    assert summary.deleted_files == 1
    assert dict(file_row) == {"is_deleted": 1, "current_size_bytes": None}
    assert dict(snapshot_row) == {"loc": None, "complexity": None}


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
