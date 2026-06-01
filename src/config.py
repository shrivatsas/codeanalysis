"""Runtime configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path

from src.analytics.database import DEFAULT_DB_PATH

DB_PATH_ENV_VAR = "CODEANALYSIS_DB_PATH"
DASHBOARD_HOST_ENV_VAR = "CODEANALYSIS_DASHBOARD_HOST"
DASHBOARD_PORT_ENV_VAR = "CODEANALYSIS_DASHBOARD_PORT"

DEFAULT_DASHBOARD_HOST = "127.0.0.1"
DEFAULT_DASHBOARD_PORT = 8000


def default_db_path() -> Path:
    value = os.getenv(DB_PATH_ENV_VAR)
    return Path(value).expanduser() if value else DEFAULT_DB_PATH


def default_dashboard_host() -> str:
    return os.getenv(DASHBOARD_HOST_ENV_VAR, DEFAULT_DASHBOARD_HOST)


def default_dashboard_port() -> int:
    value = os.getenv(DASHBOARD_PORT_ENV_VAR)
    if not value:
        return DEFAULT_DASHBOARD_PORT
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(
            f"{DASHBOARD_PORT_ENV_VAR} must be an integer."
        ) from exc
