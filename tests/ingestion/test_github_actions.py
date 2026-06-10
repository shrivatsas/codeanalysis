from __future__ import annotations

import json
import os
import subprocess
from contextlib import closing
from pathlib import Path

import pytest

from src.analytics.database import apply_migrations, connect_database
from src.ingestion.ci_loader import ingest_ci_report
from src.ingestion.github_actions import (
    _gh_api_json,
    download_github_actions_report,
)


def test_download_github_actions_report_writes_importer_friendly_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output = tmp_path / "ci.json"
    repo = _init_repo(tmp_path / "repo")
    _write(repo / "app.py", "print('hello')\n")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "Add app")
    calls: list[str] = []

    def fake_gh_api_json(endpoint: str, *, fields=None):  # noqa: ANN001
        calls.append(endpoint)
        if endpoint.endswith("/actions/runs"):
            return {
                "workflow_runs": [
                    {
                        "id": 123,
                        "name": "Build",
                        "head_branch": "main",
                        "head_sha": "abc123",
                        "status": "completed",
                        "conclusion": "success",
                        "run_started_at": "2026-05-17T10:00:00Z",
                        "updated_at": "2026-05-17T10:10:00Z",
                    }
                ]
            }
        if endpoint.endswith("/actions/runs/123"):
            return {
                "id": 123,
                "name": "Build",
                "head_branch": "main",
                "head_sha": "abc123",
                "status": "completed",
                "conclusion": "success",
                "run_started_at": "2026-05-17T10:00:00Z",
                "updated_at": "2026-05-17T10:10:00Z",
            }
        if endpoint.endswith("/actions/runs/123/jobs"):
            return {
                "jobs": [
                    {
                        "name": "unit",
                        "status": "completed",
                        "conclusion": "success",
                        "started_at": "2026-05-17T10:00:00Z",
                        "completed_at": "2026-05-17T10:08:00Z",
                    }
                ]
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(
        "src.ingestion.github_actions._gh_api_json",
        fake_gh_api_json,
    )

    summary = download_github_actions_report("owner/repo", output, branch="main")
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert summary.repository == "owner/repo"
    assert summary.run_id == 123
    assert summary.workflow_name == "Build"
    assert calls[0] == "repos/owner/repo/actions/runs"
    assert calls[-1] == "repos/owner/repo/actions/runs/123/jobs"
    assert payload["runs"][0]["pipeline_name"] == "Build"
    assert payload["runs"][0]["jobs"][0]["name"] == "unit"
    assert payload["runs"][0]["jobs"][0]["tests"] == []

    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        apply_migrations(connection)
        summary_row = ingest_ci_report(connection, repo, output)

    assert summary_row.runs == 1
    assert summary_row.jobs == 1


def test_download_github_actions_report_surfaces_gh_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output = tmp_path / "ci.json"

    def fake_run(*args, **kwargs):  # noqa: ANN001, ANN002
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=["gh", "api", "repos/owner/repo/actions/runs"],
            stderr="HTTP 404: Not Found",
        )

    monkeypatch.setattr("src.ingestion.github_actions.subprocess.run", fake_run)

    with pytest.raises(
        RuntimeError,
        match="gh api failed for repos/owner/repo/actions/runs",
    ):
        download_github_actions_report("owner/repo", output)


def test_gh_api_json_uses_get_when_fields_are_present(monkeypatch) -> None:
    commands = []

    def fake_run(cmd, **kwargs):  # noqa: ANN001, ANN003
        commands.append(cmd)

        class Result:
            stdout = "{}"

        return Result()

    monkeypatch.setattr("src.ingestion.github_actions.subprocess.run", fake_run)

    payload = _gh_api_json(
        "repos/owner/repo/actions/runs",
        fields={"status": "completed", "per_page": 20},
    )

    assert payload == {}
    assert commands[0][:4] == [
        "gh",
        "api",
        "repos/owner/repo/actions/runs",
        "-H",
    ]
    assert "-X" in commands[0]
    assert "GET" in commands[0]


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
