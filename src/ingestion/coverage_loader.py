"""Coverage artifact ingestion for local repositories."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class CoverageRecord:
    path: str
    covered_lines: int
    total_lines: int


@dataclass(frozen=True)
class CoverageImportSummary:
    repository_id: int
    repository_path: Path
    measured_at: str
    files: int
    coverage_rows: int


def ingest_coverage_report(
    connection: sqlite3.Connection,
    repo_path: str | Path,
    coverage_report_path: str | Path,
) -> CoverageImportSummary:
    """Import a JSON coverage report into SQLite."""
    resolved_repo = _resolve_repository(repo_path)
    resolved_report = Path(coverage_report_path).expanduser().resolve()
    if not resolved_report.exists():
        raise FileNotFoundError(
            f"Coverage report path does not exist: {resolved_report}"
        )

    repository_id = _upsert_repository(connection, resolved_repo)
    run_id = _start_analysis_run(connection, repository_id)

    try:
        measured_at, records = _load_coverage_report(resolved_report)
        file_count = 0
        coverage_rows = 0

        with connection:
            for record in records:
                file_id = _upsert_file(connection, repository_id, record.path)
                _upsert_coverage_row(
                    connection,
                    repository_id,
                    file_id,
                    measured_at,
                    record,
                )
                file_count += 1
                coverage_rows += 1

            _finish_analysis_run(connection, run_id, "succeeded")

    except Exception as exc:
        with connection:
            _finish_analysis_run(connection, run_id, "failed", str(exc))
        raise

    return CoverageImportSummary(
        repository_id=repository_id,
        repository_path=resolved_repo,
        measured_at=measured_at,
        files=file_count,
        coverage_rows=coverage_rows,
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


def _load_coverage_report(report_path: Path) -> tuple[str, tuple[CoverageRecord, ...]]:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        measured_at = str(payload.get("measured_at") or _current_timestamp())
        raw_records = payload.get("files", [])
    elif isinstance(payload, list):
        measured_at = _current_timestamp()
        raw_records = payload
    else:
        raise ValueError("Coverage report must be a JSON object or array.")

    if not isinstance(raw_records, list):
        raise ValueError("Coverage report files must be provided as a JSON array.")

    records = []
    for item in raw_records:
        if not isinstance(item, dict):
            raise ValueError("Coverage report entries must be JSON objects.")
        path = str(item.get("path", "")).strip()
        if not path:
            raise ValueError("Coverage report entry missing path.")
        covered_lines = _parse_non_negative_int(
            item.get("covered_lines"),
            "covered_lines",
        )
        total_lines = _parse_non_negative_int(item.get("total_lines"), "total_lines")
        records.append(
            CoverageRecord(
                path=path,
                covered_lines=covered_lines,
                total_lines=total_lines,
            )
        )

    return measured_at, tuple(records)


def _parse_non_negative_int(value: object, field_name: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"Coverage report entry has invalid {field_name}.")
    if value < 0:
        raise ValueError(f"Coverage report entry has negative {field_name}.")
    return value


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
    path: str,
) -> int:
    row = connection.execute(
        """
        INSERT INTO files (
          repository_id,
          path,
          is_deleted
        )
        VALUES (?, ?, 0)
        ON CONFLICT(repository_id, path) DO UPDATE SET
          is_deleted = excluded.is_deleted
        RETURNING id
        """,
        (repository_id, path),
    ).fetchone()
    return int(row["id"])


def _upsert_coverage_row(
    connection: sqlite3.Connection,
    repository_id: int,
    file_id: int,
    measured_at: str,
    record: CoverageRecord,
) -> None:
    connection.execute(
        """
        INSERT INTO coverage_by_file (
          repository_id,
          file_id,
          measured_at,
          covered_lines,
          total_lines
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(repository_id, file_id, measured_at) DO UPDATE SET
          covered_lines = excluded.covered_lines,
          total_lines = excluded.total_lines
        """,
        (
            repository_id,
            file_id,
            measured_at,
            record.covered_lines,
            record.total_lines,
        ),
    )


def _start_analysis_run(connection: sqlite3.Connection, repository_id: int) -> int:
    with connection:
        row = connection.execute(
            """
            INSERT INTO analysis_runs (repository_id, run_type, status)
            VALUES (?, 'coverage_ingestion', 'started')
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


def _current_branch(repo_path: Path) -> str:
    result = _run_git(repo_path, "branch", "--show-current", check=False)
    branch = result.stdout.strip()
    return branch or "HEAD"


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
        capture_output=True,
        check=check,
        text=True,
    )
