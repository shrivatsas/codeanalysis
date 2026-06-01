from __future__ import annotations

from pathlib import Path

import pytest

from src.config import (
    default_dashboard_host,
    default_dashboard_port,
    default_db_path,
)


def test_runtime_defaults_can_come_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    monkeypatch.setenv("CODEANALYSIS_DB_PATH", str(db_path))
    monkeypatch.setenv("CODEANALYSIS_DASHBOARD_HOST", "0.0.0.0")
    monkeypatch.setenv("CODEANALYSIS_DASHBOARD_PORT", "9090")

    assert default_db_path() == db_path
    assert default_dashboard_host() == "0.0.0.0"
    assert default_dashboard_port() == 9090


def test_dashboard_port_rejects_non_integer_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEANALYSIS_DASHBOARD_PORT", "invalid")

    with pytest.raises(ValueError, match="must be an integer"):
        default_dashboard_port()
