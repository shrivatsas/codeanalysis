from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.cli.cmd_download_ci import main


def test_download_ci_cli_delegates_to_downloader(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake_download(
        repository,  # noqa: ANN001
        output_path,  # noqa: ANN001
        *,
        run_id=None,  # noqa: ANN001
        branch=None,  # noqa: ANN001
        workflow=None,  # noqa: ANN001
        limit=20,  # noqa: ANN001
    ):
        captured.update(
            {
                "repository": repository,
                "output_path": Path(output_path),
                "run_id": run_id,
                "branch": branch,
                "workflow": workflow,
                "limit": limit,
            }
        )
        return SimpleNamespace(
            repository=repository,
            run_id=123,
            workflow_name="Build",
            output_path=Path(output_path),
        )

    monkeypatch.setattr(
        "src.cli.cmd_download_ci.download_github_actions_report",
        fake_download,
    )

    exit_code = main(
        [
            "--repo",
            "owner/repo",
            "--output",
            str(tmp_path / "ci.json"),
            "--branch",
            "main",
        ]
    )

    assert exit_code == 0
    assert captured["repository"] == "owner/repo"
    assert captured["output_path"] == tmp_path / "ci.json"
    assert captured["branch"] == "main"


def test_download_ci_cli_prints_clean_error(
    monkeypatch,
    capsys,
) -> None:
    def fake_download(*args, **kwargs):  # noqa: ANN001, ANN002
        raise RuntimeError("gh: Not Found (HTTP 404)")

    monkeypatch.setattr(
        "src.cli.cmd_download_ci.download_github_actions_report",
        fake_download,
    )

    exit_code = main(["--repo", "owner/repo"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert captured.err.strip() == "error: gh: Not Found (HTTP 404)"
