"""Local Git repository ingestion."""

from __future__ import annotations

import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

LOG_FIELD_SEPARATOR = "\x1f"
LOG_RECORD_SEPARATOR = "\x1e"


@dataclass(frozen=True)
class GitFileChange:
    path: str
    insertions: int
    deletions: int


@dataclass(frozen=True)
class GitCommit:
    commit_hash: str
    author_name: str
    author_email: str
    committed_at: str
    message: str
    files: tuple[GitFileChange, ...]


@dataclass(frozen=True)
class IngestionSummary:
    repository_id: int
    repository_path: Path
    commits: int
    files: int
    commit_files: int


def ingest_git_repository(
    connection: sqlite3.Connection,
    repo_path: str | Path,
) -> IngestionSummary:
    """Ingest local Git history into SQLite."""
    resolved_repo = _resolve_repository(repo_path)
    repository_id = _upsert_repository(connection, resolved_repo)
    run_id = _start_analysis_run(connection, repository_id)

    try:
        commits = _read_git_commits(resolved_repo)
        file_ids: set[int] = set()
        commit_file_count = 0

        with connection:
            for commit in commits:
                commit_id = _upsert_commit(connection, repository_id, commit)
                for file_change in commit.files:
                    file_id = _upsert_file(
                        connection, repository_id, resolved_repo, file_change.path
                    )
                    file_ids.add(file_id)
                    _upsert_commit_file(connection, commit_id, file_id, file_change)
                    commit_file_count += 1

            _finish_analysis_run(connection, run_id, "succeeded")

    except Exception as exc:
        with connection:
            _finish_analysis_run(connection, run_id, "failed", str(exc))
        raise

    return IngestionSummary(
        repository_id=repository_id,
        repository_path=resolved_repo,
        commits=len(commits),
        files=len(file_ids),
        commit_files=commit_file_count,
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


def _read_git_commits(repo_path: Path) -> list[GitCommit]:
    if not _has_commits(repo_path):
        return []

    format_spec = (
        f"{LOG_RECORD_SEPARATOR}%H"
        f"{LOG_FIELD_SEPARATOR}%an"
        f"{LOG_FIELD_SEPARATOR}%ae"
        f"{LOG_FIELD_SEPARATOR}%aI"
        f"{LOG_FIELD_SEPARATOR}%s"
    )
    result = _run_git(
        repo_path,
        "log",
        "--reverse",
        "--numstat",
        f"--format={format_spec}",
    )
    return _parse_git_log(result.stdout)


def _has_commits(repo_path: Path) -> bool:
    result = _run_git(repo_path, "rev-parse", "--verify", "HEAD", check=False)
    return result.returncode == 0


def _parse_git_log(output: str) -> list[GitCommit]:
    commits: list[GitCommit] = []
    for raw_record in output.split(LOG_RECORD_SEPARATOR):
        record = raw_record.strip()
        if not record:
            continue

        lines = record.splitlines()
        header = lines[0].split(LOG_FIELD_SEPARATOR)
        if len(header) != 5:
            raise ValueError(f"Unexpected git log header: {lines[0]}")

        files = tuple(_parse_numstat_line(line) for line in lines[1:] if line.strip())
        commits.append(
            GitCommit(
                commit_hash=header[0],
                author_name=header[1],
                author_email=header[2],
                committed_at=header[3],
                message=header[4],
                files=files,
            )
        )

    return commits


def _parse_numstat_line(line: str) -> GitFileChange:
    parts = line.split("\t")
    if len(parts) < 3:
        raise ValueError(f"Unexpected git numstat line: {line}")

    return GitFileChange(
        path=_normalize_numstat_path(parts[-1]),
        insertions=_parse_numstat_count(parts[0]),
        deletions=_parse_numstat_count(parts[1]),
    )


def _parse_numstat_count(value: str) -> int:
    if value == "-":
        return 0
    return int(value)


def _normalize_numstat_path(path: str) -> str:
    if " => " not in path:
        return path

    prefix, renamed = path.split("{", 1) if "{" in path else ("", path)
    renamed = renamed.rstrip("}")
    _old_path, new_path = renamed.split(" => ", 1)
    return f"{prefix}{new_path}"


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


def _upsert_commit(
    connection: sqlite3.Connection,
    repository_id: int,
    commit: GitCommit,
) -> int:
    row = connection.execute(
        """
        INSERT INTO commits (
          repository_id,
          commit_hash,
          author_name,
          author_email,
          committed_at,
          message,
          insertions,
          deletions,
          files_changed
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(repository_id, commit_hash) DO UPDATE SET
          author_name = excluded.author_name,
          author_email = excluded.author_email,
          committed_at = excluded.committed_at,
          message = excluded.message,
          insertions = excluded.insertions,
          deletions = excluded.deletions,
          files_changed = excluded.files_changed
        RETURNING id
        """,
        (
            repository_id,
            commit.commit_hash,
            commit.author_name,
            commit.author_email,
            commit.committed_at,
            commit.message,
            sum(file.insertions for file in commit.files),
            sum(file.deletions for file in commit.files),
            len(commit.files),
        ),
    ).fetchone()
    return int(row["id"])


def _upsert_file(
    connection: sqlite3.Connection,
    repository_id: int,
    repo_path: Path,
    file_path: str,
) -> int:
    full_path = repo_path / file_path
    is_deleted = not full_path.exists()
    size = None if is_deleted else full_path.stat().st_size

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
            file_path,
            _language_for_path(file_path),
            size,
            int(is_deleted),
        ),
    ).fetchone()
    return int(row["id"])


def _upsert_commit_file(
    connection: sqlite3.Connection,
    commit_id: int,
    file_id: int,
    file_change: GitFileChange,
) -> None:
    connection.execute(
        """
        INSERT INTO commit_files (
          commit_id,
          file_id,
          change_type,
          insertions,
          deletions
        )
        VALUES (?, ?, 'unknown', ?, ?)
        ON CONFLICT(commit_id, file_id) DO UPDATE SET
          insertions = excluded.insertions,
          deletions = excluded.deletions
        """,
        (commit_id, file_id, file_change.insertions, file_change.deletions),
    )


def _start_analysis_run(connection: sqlite3.Connection, repository_id: int) -> int:
    with connection:
        row = connection.execute(
            """
            INSERT INTO analysis_runs (repository_id, run_type, status)
            VALUES (?, 'git_ingestion', 'started')
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
        ".md": "Markdown",
        ".py": "Python",
        ".rs": "Rust",
        ".sql": "SQL",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
    }.get(suffix)


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
