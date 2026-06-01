"""Static file metrics collection for local repositories."""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_IGNORED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
}

COMPLEXITY_PATTERN = re.compile(
    r"\b(if|elif|for|while|case|catch|except|match|switch|and|or)\b|&&|\|\||\?"
)


@dataclass(frozen=True)
class StaticFileSnapshot:
    path: str
    language: str | None
    current_size_bytes: int | None
    loc: int | None
    complexity: float | None
    is_deleted: bool


@dataclass(frozen=True)
class StaticMetricsSummary:
    repository_id: int
    repository_path: Path
    files: int
    snapshots: int
    deleted_files: int


def collect_static_metrics(
    connection: sqlite3.Connection,
    repo_path: str | Path,
) -> StaticMetricsSummary:
    """Collect file metrics for a local Git repository and store snapshots."""
    resolved_repo = _resolve_repository(repo_path)
    repository_id = _upsert_repository(connection, resolved_repo)
    run_id = _start_analysis_run(connection, repository_id)

    try:
        tracked_paths = _tracked_file_paths(connection, repository_id)
        discovered_paths = _discover_file_paths(resolved_repo)
        paths = sorted(tracked_paths | discovered_paths)
        measured_at = _current_timestamp()
        files_processed = 0
        snapshots_written = 0
        deleted_files = 0

        with connection:
            for relative_path in paths:
                snapshot = _snapshot_for_path(resolved_repo, relative_path)
                file_id = _upsert_file(connection, repository_id, snapshot)
                _insert_metrics_snapshot(
                    connection,
                    repository_id,
                    file_id,
                    measured_at,
                    snapshot,
                )
                files_processed += 1
                snapshots_written += 1
                if snapshot.is_deleted:
                    deleted_files += 1

            _finish_analysis_run(connection, run_id, "succeeded")

    except Exception as exc:
        with connection:
            _finish_analysis_run(connection, run_id, "failed", str(exc))
        raise

    return StaticMetricsSummary(
        repository_id=repository_id,
        repository_path=resolved_repo,
        files=files_processed,
        snapshots=snapshots_written,
        deleted_files=deleted_files,
    )


def _resolve_repository(repo_path: str | Path) -> Path:
    resolved = Path(repo_path).expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Repository path does not exist: {resolved}")

    result = _run_git(resolved, "rev-parse", "--is-inside-work-tree")
    if result.stdout.strip() != "true":
        raise ValueError(f"Path is not inside a Git work tree: {resolved}")

    root = _run_git(resolved, "rev-parse", "--show-toplevel").stdout.strip()
    return Path(root).resolve()


def _tracked_file_paths(
    connection: sqlite3.Connection,
    repository_id: int,
) -> set[str]:
    rows = connection.execute(
        """
        SELECT path
        FROM files
        WHERE repository_id = ?
        """,
        (repository_id,),
    ).fetchall()
    return {row["path"] for row in rows}


def _discover_file_paths(repo_path: Path) -> set[str]:
    discovered: set[str] = set()

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [
            directory
            for directory in dirs
            if directory not in DEFAULT_IGNORED_DIRECTORIES
        ]
        root_path = Path(root)
        for filename in files:
            full_path = root_path / filename
            if ".git" in full_path.parts:
                continue
            discovered.add(full_path.relative_to(repo_path).as_posix())

    return discovered


def _snapshot_for_path(repo_path: Path, relative_path: str) -> StaticFileSnapshot:
    full_path = repo_path / relative_path
    if not full_path.exists() or not full_path.is_file():
        return StaticFileSnapshot(
            path=relative_path,
            language=_language_for_path(relative_path),
            current_size_bytes=None,
            loc=None,
            complexity=None,
            is_deleted=True,
        )

    raw_bytes = full_path.read_bytes()
    current_size_bytes = len(raw_bytes)

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return StaticFileSnapshot(
            path=relative_path,
            language=_language_for_path(relative_path),
            current_size_bytes=current_size_bytes,
            loc=None,
            complexity=None,
            is_deleted=False,
        )

    return StaticFileSnapshot(
        path=relative_path,
        language=_language_for_path(relative_path),
        current_size_bytes=current_size_bytes,
        loc=_loc_for_text(text),
        complexity=_complexity_for_text(text),
        is_deleted=False,
    )


def _loc_for_text(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def _complexity_for_text(text: str) -> float:
    if not text.strip():
        return 0.0
    return float(1 + len(COMPLEXITY_PATTERN.findall(text)))


def _upsert_repository(connection: sqlite3.Connection, repo_path: Path) -> int:
    default_branch = _current_branch(repo_path)
    with connection:
        row = connection.execute(
            """
            INSERT INTO repositories (name, path, default_branch)
            VALUES (?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
              name = excluded.name,
              default_branch = excluded.default_branch
            RETURNING id
            """,
            (repo_path.name, str(repo_path), default_branch),
        ).fetchone()
    return int(row["id"])


def _upsert_file(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot: StaticFileSnapshot,
) -> int:
    row = connection.execute(
        """
        INSERT INTO files (
          repository_id,
          path,
          language,
          current_size_bytes,
          is_deleted
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(repository_id, path) DO UPDATE SET
          language = excluded.language,
          current_size_bytes = excluded.current_size_bytes,
          is_deleted = excluded.is_deleted
        RETURNING id
        """,
        (
            repository_id,
            snapshot.path,
            snapshot.language,
            snapshot.current_size_bytes,
            int(snapshot.is_deleted),
        ),
    ).fetchone()
    return int(row["id"])


def _insert_metrics_snapshot(
    connection: sqlite3.Connection,
    repository_id: int,
    file_id: int,
    measured_at: str,
    snapshot: StaticFileSnapshot,
) -> None:
    connection.execute(
        """
        INSERT INTO metrics_snapshot (
          repository_id,
          file_id,
          measured_at,
          loc,
          complexity
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            repository_id,
            file_id,
            measured_at,
            snapshot.loc,
            snapshot.complexity,
        ),
    )


def _start_analysis_run(connection: sqlite3.Connection, repository_id: int) -> int:
    with connection:
        row = connection.execute(
            """
            INSERT INTO analysis_runs (repository_id, run_type, status)
            VALUES (?, 'static_metrics', 'started')
            RETURNING id
            """,
            (repository_id,),
        ).fetchone()
    return int(row["id"])


def _finish_analysis_run(
    connection: sqlite3.Connection,
    run_id: int,
    status: str,
    message: str | None = None,
) -> None:
    connection.execute(
        """
        UPDATE analysis_runs
        SET status = ?,
            finished_at = CURRENT_TIMESTAMP,
            message = ?
        WHERE id = ?
        """,
        (status, message, run_id),
    )


def _current_branch(repo_path: Path) -> str | None:
    result = _run_git(
        repo_path, "symbolic-ref", "--quiet", "--short", "HEAD", check=False
    )
    branch = result.stdout.strip()
    return branch or None


def _language_for_path(path: str) -> str | None:
    suffix = Path(path).suffix.lower()
    return {
        ".go": "Go",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".json": "JSON",
        ".md": "Markdown",
        ".py": "Python",
        ".rs": "Rust",
        ".sh": "Shell",
        ".sql": "SQL",
        ".toml": "TOML",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".yaml": "YAML",
        ".yml": "YAML",
    }.get(suffix)


def _current_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _run_git(
    repo_path: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *args),
        cwd=repo_path,
        check=check,
        capture_output=True,
        text=True,
    )
