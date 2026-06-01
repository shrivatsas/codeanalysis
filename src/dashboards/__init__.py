"""Local dashboard application modules."""

from src.dashboards.app import (
    DashboardApplication,
    create_dashboard_app,
    serve_dashboard,
)

__all__ = [
    "DashboardApplication",
    "create_dashboard_app",
    "serve_dashboard",
]
