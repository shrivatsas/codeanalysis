from __future__ import annotations

import json
import os
import subprocess
from contextlib import closing
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.analytics.database import apply_migrations, connect_database
from src.analytics.static_metrics import collect_static_metrics
from src.cli.cmd_serve_dashboard import main as serve_dashboard_main
from src.dashboards.app import create_dashboard_app
from src.ingestion.ci_loader import ingest_ci_report
from src.ingestion.git_loader import ingest_git_repository


def test_dashboard_empty_state_renders_navigation() -> None:
    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        apply_migrations(connection)
        app = create_dashboard_app(connection)

        home_status, _, home_body = _request(app, "/")
        status, headers, body = _request(app, "/risk")

    assert home_status == "200 OK"
    assert status == "200 OK"
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    assert 'rel="icon"' in home_body
    assert "Top Risk Preview" not in home_body
    assert "/ci" in home_body
    assert "summary-line" in home_body
    assert "Risk Leaderboard" in body
    assert "No risk rows available yet" in body
    assert "Hotspots" in body


def test_dashboard_renders_seeded_repo_and_file_detail(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    _write(
        repo / "app.py",
        "def add(a, b):\n    if a > b:\n        return a\n    return b\n",
    )
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "Add app")

    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        apply_migrations(connection)

        ingest_git_repository(connection, repo)
        collect_static_metrics(connection, repo)
        app = create_dashboard_app(connection)

        risk_status, _, risk_body = _request(app, "/risk")
        hotspots_status, _, hotspots_body = _request(app, "/hotspots")
        ownership_status, _, ownership_body = _request(app, "/ownership")
        ci_status, _, ci_body = _request(app, "/ci")
        file_status, _, file_body = _request(
            app,
            "/file?repository_id=1&path=app.py",
        )

    assert risk_status == "200 OK"
    assert hotspots_status == "200 OK"
    assert ownership_status == "200 OK"
    assert ci_status == "200 OK"
    assert file_status == "200 OK"
    assert "app.py" in risk_body
    assert "app.py" in hotspots_body
    assert "Ownership" in ownership_body
    assert "Pipeline Health" in ci_body
    assert "File Detail: app.py" in file_body
    assert "Risk score" in file_body


def test_dashboard_renders_ci_page_and_controls(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    _write(repo / "app.py", "def add(a, b):\n    return a + b\n")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "Add app")

    ci_report = tmp_path / "ci.json"
    _write_ci_report(
        ci_report,
        {
            "runs": [
                {
                    "pipeline_name": "Build",
                    "run_key": "build-1",
                    "branch": "main",
                    "commit_hash": "abc123",
                    "status": "passed",
                    "started_at": "2026-05-17T10:00:00Z",
                    "finished_at": "2026-05-17T10:05:00Z",
                    "duration_seconds": 300,
                    "jobs": [
                        {
                            "job_name": "unit",
                            "status": "passed",
                            "started_at": "2026-05-17T10:00:00Z",
                            "finished_at": "2026-05-17T10:04:00Z",
                            "duration_seconds": 240,
                            "tests": [
                                {
                                    "test_name": "test_add",
                                    "status": "passed",
                                    "duration_seconds": 1.2,
                                }
                            ],
                        }
                    ],
                },
                {
                    "pipeline_name": "Deploy",
                    "run_key": "deploy-1",
                    "branch": "main",
                    "commit_hash": "abc124",
                    "status": "failed",
                    "started_at": "2026-05-18T10:00:00Z",
                    "finished_at": "2026-05-18T10:09:00Z",
                    "duration_seconds": 540,
                    "jobs": [
                        {
                            "job_name": "deploy",
                            "status": "failed",
                            "started_at": "2026-05-18T10:00:00Z",
                            "finished_at": "2026-05-18T10:09:00Z",
                            "duration_seconds": 540,
                            "failure_reason": "failed",
                            "tests": [],
                        }
                    ],
                },
            ]
        },
    )

    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        apply_migrations(connection)
        ingest_git_repository(connection, repo)
        ingest_ci_report(connection, repo, ci_report)
        app = create_dashboard_app(connection)

        ci_status, _, ci_body = _request(app, "/ci")
        filtered_status, _, filtered_body = _request(
            app,
            "/ci?health_q=Deploy&run_q=Deploy&health_sort=pipeline_name&health_order=asc&run_sort=pipeline_name&run_order=asc",
        )

    assert ci_status == "200 OK"
    assert filtered_status == "200 OK"
    assert "Pipeline Health" in ci_body
    assert "Recent Runs" in ci_body
    assert "Build" in ci_body
    assert "Deploy" in ci_body
    assert "failure rate" in ci_body.lower()
    assert "Build" not in filtered_body
    assert "Deploy" in filtered_body
    assert filtered_body.count("Deploy") >= 2


def test_dashboard_filters_and_sorts_repository_table(tmp_path: Path) -> None:
    alpha_repo = _init_repo(tmp_path / "alpha-repo")
    _write(alpha_repo / "alpha.py", "def alpha():\n    return 1\n")
    _git(alpha_repo, "add", "alpha.py")
    _git(alpha_repo, "commit", "-m", "Alpha")

    zeta_repo = _init_repo(tmp_path / "zeta-repo")
    _write(zeta_repo / "zeta.py", "def zeta():\n    return 2\n")
    _git(zeta_repo, "add", "zeta.py")
    _git(zeta_repo, "commit", "-m", "Zeta")

    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        apply_migrations(connection)
        ingest_git_repository(connection, alpha_repo)
        ingest_git_repository(connection, zeta_repo)
        app = create_dashboard_app(connection)

        asc_status, _, asc_body = _request(
            app,
            "/?repo_q=repo&repo_sort=name&repo_order=asc",
        )
        desc_status, _, desc_body = _request(
            app,
            "/?repo_q=repo&repo_sort=name&repo_order=desc",
        )
        filtered_status, _, filtered_body = _request(
            app,
            "/?repo_q=alpha-repo&repo_sort=name&repo_order=asc",
        )

    assert asc_status == "200 OK"
    assert desc_status == "200 OK"
    assert filtered_status == "200 OK"
    assert asc_body.index(str(alpha_repo)) < asc_body.index(str(zeta_repo))
    assert desc_body.index(str(zeta_repo)) < desc_body.index(str(alpha_repo))
    assert str(alpha_repo) in filtered_body
    assert str(zeta_repo) not in filtered_body
def test_dashboard_filters_and_sorts_risk_table(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    _write(
        repo / "zeta.py",
        "def zeta():\n    if True:\n        return 2\n    return 0\n",
    )
    _write(
        repo / "alpha.py",
        "def alpha():\n    if True:\n        return 1\n    return 0\n",
    )
    _git(repo, "add", "alpha.py", "zeta.py")
    _git(repo, "commit", "-m", "Add files")

    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        apply_migrations(connection)
        ingest_git_repository(connection, repo)
        collect_static_metrics(connection, repo)
        app = create_dashboard_app(connection)

        asc_status, _, asc_body = _request(
            app,
            "/risk?sort=path&order=asc",
        )
        filtered_status, _, filtered_body = _request(
            app,
            "/risk?q=alpha&sort=path&order=asc",
        )

    assert asc_status == "200 OK"
    assert filtered_status == "200 OK"
    assert "alpha.py" in asc_body
    assert "zeta.py" in asc_body
    assert asc_body.index("alpha.py") < asc_body.index("zeta.py")
    assert "alpha.py" in filtered_body
    assert "zeta.py" not in filtered_body


def test_dashboard_cli_delegates_to_server(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_serve_dashboard(db_path, *, host, port):
        captured["db_path"] = db_path
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr(
        "src.cli.cmd_serve_dashboard.serve_dashboard",
        fake_serve_dashboard,
    )

    exit_code = serve_dashboard_main(
        ["--db", "data/demo.db", "--host", "0.0.0.0", "--port", "9090"]
    )

    assert exit_code == 0
    assert str(captured["db_path"]) == "data/demo.db"
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9090


def _request(app, path: str):
    parsed = urlparse(path)
    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": parsed.path,
        "QUERY_STRING": parsed.query,
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "80",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": BytesIO(b""),
        "wsgi.errors": BytesIO(),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }
    headers: dict[str, str] = {}
    status_holder: dict[str, str] = {}

    def start_response(status, response_headers, exc_info=None):  # noqa: ANN001
        status_holder["status"] = status
        headers.update(dict(response_headers))

    body = b"".join(app(environ, start_response)).decode("utf-8")
    return status_holder["status"], headers, body


def _init_repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init")
    _git(path, "config", "user.name", "Ada Lovelace")
    _git(path, "config", "user.email", "ada@example.com")
    return path


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _write_ci_report(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


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
