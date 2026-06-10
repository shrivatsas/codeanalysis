"""CI/CD artifact ingestion for local repositories."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CITestResult:
    test_name: str
    status: str
    started_at: str | None
    finished_at: str | None
    duration_seconds: float | None
    failure_reason: str | None


@dataclass(frozen=True)
class CIJobRun:
    job_name: str
    status: str
    started_at: str | None
    finished_at: str | None
    duration_seconds: float | None
    failure_reason: str | None
    tests: tuple[CITestResult, ...]


@dataclass(frozen=True)
class CIPipelineRun:
    pipeline_name: str
    run_key: str
    branch: str | None
    commit_hash: str | None
    status: str
    started_at: str
    finished_at: str | None
    duration_seconds: float | None
    jobs: tuple[CIJobRun, ...]


@dataclass(frozen=True)
class CIImportSummary:
    repository_id: int
    repository_path: Path
    runs: int
    jobs: int
    test_results: int


def ingest_ci_report(
    connection: sqlite3.Connection,
    repo_path: str | Path,
    ci_report_path: str | Path,
) -> CIImportSummary:
    """Import a JSON CI/CD summary into SQLite."""
    resolved_repo = _resolve_repository(repo_path)
    resolved_report = Path(ci_report_path).expanduser().resolve()
    if not resolved_report.exists():
        raise FileNotFoundError(f"CI report path does not exist: {resolved_report}")

    repository_id = _upsert_repository(connection, resolved_repo)
    run_id = _start_analysis_run(connection, repository_id)

    try:
        pipeline_runs = _load_ci_report(resolved_report)
        run_count = 0
        job_count = 0
        test_result_count = 0

        with connection:
            for pipeline_run in pipeline_runs:
                pipeline_run_id = _upsert_pipeline_run(
                    connection,
                    repository_id,
                    pipeline_run,
                )
                run_count += 1
                for job_run in pipeline_run.jobs:
                    job_run_id = _upsert_job_run(
                        connection,
                        pipeline_run_id,
                        job_run,
                    )
                    job_count += 1
                    for test_result in job_run.tests:
                        _upsert_test_result(
                            connection,
                            job_run_id,
                            test_result,
                        )
                        test_result_count += 1

            _finish_analysis_run(connection, run_id, "succeeded")

    except Exception as exc:
        with connection:
            _finish_analysis_run(connection, run_id, "failed", str(exc))
        raise

    return CIImportSummary(
        repository_id=repository_id,
        repository_path=resolved_repo,
        runs=run_count,
        jobs=job_count,
        test_results=test_result_count,
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


def _load_ci_report(report_path: Path) -> tuple[CIPipelineRun, ...]:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        raw_runs = payload.get("runs")
        if raw_runs is None:
            raw_runs = [payload]
    elif isinstance(payload, list):
        raw_runs = payload
    else:
        raise ValueError("CI report must be a JSON object or array.")

    if not isinstance(raw_runs, list):
        raise ValueError("CI report runs must be provided as a JSON array.")

    return tuple(_parse_pipeline_run(item) for item in raw_runs)


def _parse_pipeline_run(item: object) -> CIPipelineRun:
    if not isinstance(item, dict):
        raise ValueError("CI report runs must be JSON objects.")

    pipeline_name = str(item.get("pipeline_name", "")).strip()
    if not pipeline_name:
        raise ValueError("CI report entry missing pipeline_name.")

    run_key = _parse_required_string(
        item,
        ("run_key", "run_id", "id", "started_at"),
        "run_key",
    )
    started_at = _parse_required_string(item, ("started_at",), "started_at")
    status = _parse_status(
        item.get("status"),
        {"queued", "running", "passed", "failed", "canceled"},
    )
    jobs = tuple(
        _parse_job_run(job) for job in _parse_optional_list(item.get("jobs"))
    )
    return CIPipelineRun(
        pipeline_name=pipeline_name,
        run_key=run_key,
        branch=_parse_optional_string(item.get("branch")),
        commit_hash=_parse_optional_string(item.get("commit_hash")),
        status=status,
        started_at=started_at,
        finished_at=_parse_optional_string(item.get("finished_at")),
        duration_seconds=_parse_optional_float(item.get("duration_seconds")),
        jobs=jobs,
    )


def _parse_job_run(item: object) -> CIJobRun:
    if not isinstance(item, dict):
        raise ValueError("CI job entries must be JSON objects.")

    job_name = str(item.get("job_name") or item.get("name") or "").strip()
    if not job_name:
        raise ValueError("CI job entry missing job_name.")

    status = _parse_status(
        item.get("status"),
        {"queued", "running", "passed", "failed", "canceled", "skipped"},
    )
    tests = tuple(
        _parse_test_result(test_result)
        for test_result in _parse_optional_list(item.get("tests"))
    )
    return CIJobRun(
        job_name=job_name,
        status=status,
        started_at=_parse_optional_string(item.get("started_at")),
        finished_at=_parse_optional_string(item.get("finished_at")),
        duration_seconds=_parse_optional_float(item.get("duration_seconds")),
        failure_reason=_parse_optional_string(item.get("failure_reason")),
        tests=tests,
    )


def _parse_test_result(item: object) -> CITestResult:
    if not isinstance(item, dict):
        raise ValueError("CI test entries must be JSON objects.")

    test_name = str(item.get("test_name") or item.get("name") or "").strip()
    if not test_name:
        raise ValueError("CI test entry missing test_name.")

    return CITestResult(
        test_name=test_name,
        status=_parse_status(item.get("status"), {"passed", "failed", "skipped"}),
        started_at=_parse_optional_string(item.get("started_at")),
        finished_at=_parse_optional_string(item.get("finished_at")),
        duration_seconds=_parse_optional_float(item.get("duration_seconds")),
        failure_reason=_parse_optional_string(item.get("failure_reason")),
    )


def _parse_required_string(
    item: dict[str, object],
    keys: tuple[str, ...],
    field_name: str,
) -> str:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    raise ValueError(f"CI report entry missing {field_name}.")


def _parse_optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if value < 0:
            raise ValueError("CI report entry has negative duration_seconds.")
        return float(value)
    raise ValueError("CI report entry has invalid duration_seconds.")


def _parse_status(value: object, allowed: set[str]) -> str:
    status = str(value or "").strip().lower()
    if not status or status not in allowed:
        raise ValueError(f"CI report entry has invalid status: {value!r}")
    return status


def _parse_optional_list(value: object) -> list[object]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("CI report nested entries must be arrays.")
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


def _upsert_pipeline_run(
    connection: sqlite3.Connection,
    repository_id: int,
    pipeline_run: CIPipelineRun,
) -> int:
    row = connection.execute(
        """
        INSERT INTO pipeline_runs (
          repository_id,
          pipeline_name,
          run_key,
          branch,
          commit_hash,
          status,
          started_at,
          finished_at,
          duration_seconds
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(repository_id, pipeline_name, run_key) DO UPDATE SET
          branch = excluded.branch,
          commit_hash = excluded.commit_hash,
          status = excluded.status,
          started_at = excluded.started_at,
          finished_at = excluded.finished_at,
          duration_seconds = excluded.duration_seconds
        RETURNING id
        """,
        (
            repository_id,
            pipeline_run.pipeline_name,
            pipeline_run.run_key,
            pipeline_run.branch,
            pipeline_run.commit_hash,
            pipeline_run.status,
            pipeline_run.started_at,
            pipeline_run.finished_at,
            pipeline_run.duration_seconds,
        ),
    ).fetchone()
    return int(row["id"])


def _upsert_job_run(
    connection: sqlite3.Connection,
    pipeline_run_id: int,
    job_run: CIJobRun,
) -> int:
    row = connection.execute(
        """
        INSERT INTO job_runs (
          pipeline_run_id,
          job_name,
          status,
          started_at,
          finished_at,
          duration_seconds,
          failure_reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(pipeline_run_id, job_name) DO UPDATE SET
          status = excluded.status,
          started_at = excluded.started_at,
          finished_at = excluded.finished_at,
          duration_seconds = excluded.duration_seconds,
          failure_reason = excluded.failure_reason
        RETURNING id
        """,
        (
            pipeline_run_id,
            job_run.job_name,
            job_run.status,
            job_run.started_at,
            job_run.finished_at,
            job_run.duration_seconds,
            job_run.failure_reason,
        ),
    ).fetchone()
    job_run_id = int(row["id"])
    for test_result in job_run.tests:
        _upsert_test_result(connection, job_run_id, test_result)
    return job_run_id


def _upsert_test_result(
    connection: sqlite3.Connection,
    job_run_id: int,
    test_result: CITestResult,
) -> None:
    connection.execute(
        """
        INSERT INTO test_results (
          job_run_id,
          test_name,
          status,
          started_at,
          finished_at,
          duration_seconds,
          failure_reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_run_id, test_name) DO UPDATE SET
          status = excluded.status,
          started_at = excluded.started_at,
          finished_at = excluded.finished_at,
          duration_seconds = excluded.duration_seconds,
          failure_reason = excluded.failure_reason
        """,
        (
            job_run_id,
            test_result.test_name,
            test_result.status,
            test_result.started_at,
            test_result.finished_at,
            test_result.duration_seconds,
            test_result.failure_reason,
        ),
    )


def _start_analysis_run(connection: sqlite3.Connection, repository_id: int) -> int:
    with connection:
        row = connection.execute(
            """
            INSERT INTO analysis_runs (repository_id, run_type, status)
            VALUES (?, 'ci_ingestion', 'started')
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
