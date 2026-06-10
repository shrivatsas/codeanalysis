"""Download CI summaries from GitHub Actions into importer-friendly JSON."""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GitHubCIExportSummary:
    repository: str
    run_id: int
    workflow_name: str
    output_path: Path
    jobs: int
    test_results: int


def download_github_actions_report(
    repository: str,
    output_path: str | Path,
    *,
    run_id: int | None = None,
    branch: str | None = None,
    workflow: str | None = None,
    limit: int = 20,
) -> GitHubCIExportSummary:
    """Download a GitHub Actions run and write it in importer format."""
    if run_id is None:
        workflow_run = _select_latest_workflow_run(
            repository,
            branch=branch,
            workflow=workflow,
            limit=limit,
        )
        run_id = int(workflow_run["id"])
    else:
        workflow_run = _gh_api_json(f"repos/{repository}/actions/runs/{run_id}")

    jobs_payload = _gh_api_json(
        f"repos/{repository}/actions/runs/{run_id}/jobs",
        fields={"per_page": 100},
    )
    artifact = _build_ci_artifact(workflow_run, jobs_payload)

    resolved_output = Path(output_path).expanduser().resolve()
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output.write_text(
        json.dumps(artifact, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return GitHubCIExportSummary(
        repository=repository,
        run_id=run_id,
        workflow_name=str(workflow_run.get("name") or "GitHub Actions"),
        output_path=resolved_output,
        jobs=len(artifact["runs"][0]["jobs"]),
        test_results=sum(
            len(job.get("tests", [])) for job in artifact["runs"][0]["jobs"]
        ),
    )


def _select_latest_workflow_run(
    repository: str,
    *,
    branch: str | None,
    workflow: str | None,
    limit: int,
) -> dict[str, Any]:
    fields: dict[str, str | int] = {"status": "completed", "per_page": limit}
    if branch:
        fields["branch"] = branch
    payload = _gh_api_json(f"repos/{repository}/actions/runs", fields=fields)
    runs = payload.get("workflow_runs", [])
    if not isinstance(runs, list) or not runs:
        raise ValueError(
            f"No GitHub Actions runs found for {repository}"
            + (f" on branch {branch}" if branch else "")
        )

    if workflow:
        for run in runs:
            if isinstance(run, dict) and str(run.get("name")) == workflow:
                return run
        raise ValueError(
            f"No GitHub Actions run named {workflow!r} found for {repository}"
        )

    first = runs[0]
    if not isinstance(first, dict):
        raise ValueError("Unexpected GitHub Actions payload.")
    return first


def _build_ci_artifact(
    workflow_run: dict[str, Any],
    jobs_payload: dict[str, Any],
) -> dict[str, Any]:
    jobs = jobs_payload.get("jobs", [])
    if not isinstance(jobs, list):
        raise ValueError("Unexpected GitHub Actions jobs payload.")

    pipeline_run = {
        "pipeline_name": str(workflow_run.get("name") or "GitHub Actions"),
        "run_key": str(workflow_run.get("id")),
        "branch": _optional_string(workflow_run.get("head_branch")),
        "commit_hash": _optional_string(workflow_run.get("head_sha")),
        "status": _map_run_status(
            _optional_string(workflow_run.get("status")),
            _optional_string(workflow_run.get("conclusion")),
        ),
        "started_at": _required_timestamp(
            workflow_run.get("run_started_at"),
            workflow_run.get("created_at"),
        ),
        "finished_at": _optional_string(workflow_run.get("updated_at")),
        "duration_seconds": _duration_seconds(
            workflow_run.get("run_started_at"),
            workflow_run.get("updated_at"),
        ),
        "jobs": [_build_job(job) for job in jobs if isinstance(job, dict)],
    }
    return {"runs": [pipeline_run]}


def _build_job(job: dict[str, Any]) -> dict[str, Any]:
    started_at = _optional_string(job.get("started_at"))
    finished_at = _optional_string(job.get("completed_at"))
    return {
        "name": str(job.get("name") or "job"),
        "status": _map_job_status(
            _optional_string(job.get("status")),
            _optional_string(job.get("conclusion")),
        ),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": _duration_seconds(started_at, finished_at),
        "failure_reason": _optional_string(job.get("conclusion")),
        "tests": [],
    }


def _map_run_status(status: str | None, conclusion: str | None) -> str:
    normalized_status = (status or "").lower()
    normalized_conclusion = (conclusion or "").lower()
    if normalized_status in {"queued", "requested"}:
        return "queued"
    if normalized_status in {"in_progress", "waiting"}:
        return "running"
    if normalized_status == "completed":
        if normalized_conclusion == "success":
            return "passed"
        if normalized_conclusion == "cancelled":
            return "canceled"
        return "failed"
    if normalized_conclusion == "success":
        return "passed"
    if normalized_conclusion == "cancelled":
        return "canceled"
    return "failed"


def _map_job_status(status: str | None, conclusion: str | None) -> str:
    normalized_status = (status or "").lower()
    normalized_conclusion = (conclusion or "").lower()
    if normalized_status in {"queued", "requested"}:
        return "queued"
    if normalized_status in {"in_progress", "waiting"}:
        return "running"
    if normalized_status == "completed":
        if normalized_conclusion == "success":
            return "passed"
        if normalized_conclusion == "cancelled":
            return "canceled"
        return "failed"
    if normalized_conclusion == "success":
        return "passed"
    if normalized_conclusion == "cancelled":
        return "canceled"
    return "failed"


def _required_timestamp(*values: object) -> str:
    for value in values:
        text = _optional_string(value)
        if text:
            return text
    raise ValueError("GitHub Actions payload missing timestamp.")


def _duration_seconds(started_at: object, finished_at: object) -> float | None:
    started = _parse_datetime(started_at)
    finished = _parse_datetime(finished_at)
    if started is None or finished is None:
        return None
    return max((finished - started).total_seconds(), 0.0)


def _parse_datetime(value: object) -> datetime | None:
    text = _optional_string(value)
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _gh_api_json(
    endpoint: str,
    *,
    fields: dict[str, str | int] | None = None,
) -> dict[str, Any]:
    cmd = ["gh", "api", endpoint, "-H", "Accept: application/vnd.github+json"]
    if fields:
        cmd.extend(["-X", "GET"])
    for key, value in (fields or {}).items():
        cmd.extend(["-f", f"{key}={value}"])
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "GitHub CLI 'gh' is not installed. Install it and run `gh auth login`."
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or exc.stdout or "").strip()
        message = (
            f"gh api failed for {endpoint} "
            f"({shlex.join(cmd)}; exit status {exc.returncode})."
        )
        if stderr:
            message = f"{message}\n{stderr}"
        raise RuntimeError(message) from exc
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise ValueError("Expected GitHub API to return a JSON object.")
    return payload
