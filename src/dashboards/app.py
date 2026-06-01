"""Local dashboard application for codeanalysis."""

from __future__ import annotations

import html
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode
from wsgiref.simple_server import make_server

from src.analytics.database import DEFAULT_DB_PATH, apply_migrations, connect_database
from src.config import (
    default_dashboard_host,
    default_dashboard_port,
    default_db_path,
)

_HEADER_COLUMNS = (
    "Rank",
    "Path",
    "Risk",
    "Hotspot",
    "Entropy",
    "Recent",
    "Coverage Gap",
)


@dataclass(frozen=True)
class DashboardConfig:
    db_path: Path = DEFAULT_DB_PATH
    host: str = "127.0.0.1"
    port: int = 8000


class DashboardApplication:
    """WSGI application that renders the local dashboard."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def __call__(self, environ: dict[str, Any], start_response: Any) -> list[bytes]:
        method = environ.get("REQUEST_METHOD", "GET").upper()
        if method not in {"GET", "HEAD"}:
            return self._respond(
                start_response,
                "405 Method Not Allowed",
                "text/plain; charset=utf-8",
                "Only GET and HEAD are supported.",
                method == "HEAD",
                headers=[("Allow", "GET, HEAD")],
            )

        path = environ.get("PATH_INFO", "/") or "/"
        query = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)

        if path in {"/", ""}:
            return self._render_home(start_response, query, method == "HEAD")
        if path in {"/risk", "/risk-leaderboard"}:
            return self._render_risk(start_response, query, method == "HEAD")
        if path in {"/hotspots", "/hotspot-map"}:
            return self._render_hotspots(start_response, query, method == "HEAD")
        if path in {"/ownership", "/ownership-summary"}:
            return self._render_ownership(start_response, query, method == "HEAD")
        if path in {"/file", "/files"}:
            return self._render_file_detail(
                start_response,
                query,
                method == "HEAD",
            )

        return self._respond(
            start_response,
            "404 Not Found",
            "text/plain; charset=utf-8",
            "Not found.",
            method == "HEAD",
        )

    def _render_home(
        self,
        start_response: Any,
        query: dict[str, list[str]],
        head_only: bool,
    ) -> list[bytes]:
        repository_id = self._parse_int(query.get("repository_id", [""])[0])
        repo_query = query.get("repo_q", [""])[0]
        repo_sort = query.get("repo_sort", ["created_at"])[0]
        repo_order = query.get("repo_order", ["desc"])[0]
        repositories = self._repository_rows(repo_query, repo_sort, repo_order)
        stats = self._fetch_one(
            """
            SELECT
              (SELECT COUNT(*) FROM repositories) AS repositories,
              (SELECT COUNT(*) FROM files) AS files,
              (SELECT COUNT(*) FROM metrics_snapshot) AS snapshots,
              (SELECT COUNT(*) FROM analysis_runs) AS runs,
              (SELECT COUNT(*) FROM risk_leaderboard) AS risk_rows
            """
        )
        selected_repository = None
        if repository_id is not None:
            selected_repository = self._fetch_one(
                """
                SELECT id, name, path, default_branch, created_at
                FROM repositories
                WHERE id = ?
                """,
                (repository_id,),
            )
        if repository_id is not None and selected_repository is None:
            selected_banner = self._empty_state(
                f"Repository {repository_id} not found."
            )
        elif selected_repository is not None:
            selected_banner = self._repository_focus(selected_repository)
        else:
            selected_banner = self._empty_state(
                "Select a repository below to open its dashboard."
            )
        body = [
            self._page_title("Codeanalysis Dashboard"),
            self._render_nav("home", repository_id),
            self._section(
                "Repositories",
                self._render_repository_list(
                    repositories,
                    controls_html=self._table_controls(
                        action="/",
                        repository_id=repository_id,
                        search_name="repo_q",
                        search_value=repo_query,
                        search_placeholder="Filter repositories by name or path",
                        sort_name="repo_sort",
                        sort_value=repo_sort,
                        sort_options=(
                            ("created_at", "Created"),
                            ("name", "Name"),
                            ("path", "Path"),
                        ),
                        order_name="repo_order",
                        order_value=repo_order,
                    ),
                ),
            ),
            selected_banner,
            self._summary_line(
                [
                    ("Repositories", stats["repositories"]),
                    ("Files", stats["files"]),
                    ("Snapshots", stats["snapshots"]),
                    ("Runs", stats["runs"]),
                ]
            ),
            self._section("How to Read This Dashboard", self._metric_guide()),
        ]
        return self._respond(
            start_response,
            "200 OK",
            "text/html; charset=utf-8",
            self._document("Codeanalysis Dashboard", "".join(body)),
            head_only,
        )

    def _render_risk(
        self,
        start_response: Any,
        query: dict[str, list[str]],
        head_only: bool,
    ) -> list[bytes]:
        repository_id = self._parse_int(query.get("repository_id", [""])[0])
        search_query = query.get("q", [""])[0]
        sort_key = query.get("sort", ["risk_score"])[0]
        sort_order = query.get("order", ["desc"])[0]
        rows = self._risk_rows(repository_id, search_query, sort_key, sort_order)
        body = [
            self._page_title("Risk Leaderboard"),
            self._render_nav("risk", repository_id),
            self._filter_banner(repository_id),
            self._section(
                "Ranked Files",
                self._render_table(
                    _HEADER_COLUMNS,
                    rows,
                    controls_html=self._table_controls(
                        action="/risk",
                        repository_id=repository_id,
                        search_name="q",
                        search_value=search_query,
                        search_placeholder="Filter by path",
                        sort_name="sort",
                        sort_value=sort_key,
                        sort_options=(
                            ("risk_score", "Risk score"),
                            ("hotspot_score", "Hotspot score"),
                            ("ownership_entropy", "Ownership entropy"),
                            ("recent_change_risk", "Recent change"),
                            ("coverage_gap", "Coverage gap"),
                            ("path", "Path"),
                        ),
                        order_name="order",
                        order_value=sort_order,
                    ),
                    empty_message=(
                        "No risk rows available yet. Collect metrics and "
                        "ingest history."
                    ),
                ),
            ),
        ]
        return self._respond(
            start_response,
            "200 OK",
            "text/html; charset=utf-8",
            self._document("Risk Leaderboard", "".join(body)),
            head_only,
        )

    def _render_hotspots(
        self,
        start_response: Any,
        query: dict[str, list[str]],
        head_only: bool,
    ) -> list[bytes]:
        repository_id = self._parse_int(query.get("repository_id", [""])[0])
        search_query = query.get("q", [""])[0]
        sort_key = query.get("sort", ["hotspot_score"])[0]
        sort_order = query.get("order", ["desc"])[0]
        rows = self._hotspot_rows(repository_id, search_query, sort_key, sort_order)
        body = [
            self._page_title("Hotspot Map"),
            self._render_nav("hotspots", repository_id),
            self._filter_banner(repository_id),
            self._section(
                "Churn x Complexity",
                self._render_table(
                    (
                        "Path",
                        "Churn",
                        "Insertions",
                        "Deletions",
                        "Commits",
                        "Complexity",
                        "Hotspot",
                    ),
                    rows,
                    controls_html=self._table_controls(
                        action="/hotspots",
                        repository_id=repository_id,
                        search_name="q",
                        search_value=search_query,
                        search_placeholder="Filter by path",
                        sort_name="sort",
                        sort_value=sort_key,
                        sort_options=(
                            ("hotspot_score", "Hotspot score"),
                            ("churn", "Churn"),
                            ("complexity", "Complexity"),
                            ("path", "Path"),
                        ),
                        order_name="order",
                        order_value=sort_order,
                    ),
                    empty_message=(
                        "No hotspot rows available yet. Collect metrics "
                        "first."
                    ),
                )
            ),
        ]
        return self._respond(
            start_response,
            "200 OK",
            "text/html; charset=utf-8",
            self._document("Hotspot Map", "".join(body)),
            head_only,
        )

    def _render_ownership(
        self,
        start_response: Any,
        query: dict[str, list[str]],
        head_only: bool,
    ) -> list[bytes]:
        repository_id = self._parse_int(query.get("repository_id", [""])[0])
        search_query = query.get("q", [""])[0]
        sort_key = query.get("sort", ["ownership_entropy"])[0]
        sort_order = query.get("order", ["desc"])[0]
        rows = self._ownership_rows(repository_id, search_query, sort_key, sort_order)
        body = [
            self._page_title("Ownership"),
            self._render_nav("ownership", repository_id),
            self._filter_banner(repository_id),
            self._section(
                "Contribution Entropy",
                self._render_table(
                    (
                        "Path",
                        "Total Contribution",
                        "Authors",
                        "Entropy",
                    ),
                    rows,
                    controls_html=self._table_controls(
                        action="/ownership",
                        repository_id=repository_id,
                        search_name="q",
                        search_value=search_query,
                        search_placeholder="Filter by path",
                        sort_name="sort",
                        sort_value=sort_key,
                        sort_options=(
                            ("ownership_entropy", "Entropy"),
                            ("total_contribution", "Contribution"),
                            ("contributing_authors", "Authors"),
                            ("path", "Path"),
                        ),
                        order_name="order",
                        order_value=sort_order,
                    ),
                    empty_message=(
                        "No ownership rows available yet. Ingest commit "
                        "history first."
                    ),
                )
            ),
        ]
        return self._respond(
            start_response,
            "200 OK",
            "text/html; charset=utf-8",
            self._document("Ownership", "".join(body)),
            head_only,
        )

    def _render_file_detail(
        self,
        start_response: Any,
        query: dict[str, list[str]],
        head_only: bool,
    ) -> list[bytes]:
        repository_id = self._parse_int(query.get("repository_id", [""])[0])
        path = query.get("path", [""])[0]
        if repository_id is None or not path:
            return self._respond(
                start_response,
                "400 Bad Request",
                "text/plain; charset=utf-8",
                "Provide repository_id and path query parameters.",
                head_only,
            )

        row = self._fetch_one(
            """
            SELECT
              f.path,
              f.language,
              f.current_size_bytes,
              f.is_deleted,
              lfm.measured_at,
              lfm.loc,
              lfm.complexity,
              lfm.duplication,
              lfm.fan_in,
              lfm.fan_out,
              fc.churn,
              fc.insertions,
              fc.deletions,
              fc.commits_touched,
              h.hotspot_score,
              oe.total_contribution,
              oe.contributing_authors,
              oe.ownership_entropy,
              rc.recent_change_risk,
              lcbf.covered_lines,
              lcbf.total_lines,
              lcbf.uncovered_ratio,
              cg.coverage_gap,
              rl.risk_score
            FROM files AS f
            LEFT JOIN latest_file_metrics AS lfm ON lfm.file_id = f.id
            LEFT JOIN file_churn AS fc ON fc.file_id = f.id
            LEFT JOIN hotspots AS h ON h.file_id = f.id
            LEFT JOIN ownership_entropy AS oe ON oe.file_id = f.id
            LEFT JOIN recent_change_risk AS rc ON rc.file_id = f.id
            LEFT JOIN latest_coverage_by_file AS lcbf ON lcbf.file_id = f.id
            LEFT JOIN coverage_gap AS cg ON cg.file_id = f.id
            LEFT JOIN risk_leaderboard AS rl ON rl.file_id = f.id
            WHERE f.repository_id = ? AND f.path = ?
            """,
            (repository_id, path),
        )
        if row is None:
            return self._respond(
                start_response,
                "404 Not Found",
                "text/plain; charset=utf-8",
                "File not found.",
                head_only,
            )

        details = [
            ("Repository ID", repository_id),
            ("Path", row["path"]),
            ("Language", row["language"] or "Unknown"),
            ("Deleted", "Yes" if row["is_deleted"] else "No"),
            (
                "Size bytes",
                row["current_size_bytes"]
                if row["current_size_bytes"] is not None
                else "Unknown",
            ),
            ("LOC", row["loc"] if row["loc"] is not None else "Unknown"),
            ("Complexity", self._format_number(row["complexity"])),
            ("Churn", self._format_number(row["churn"])),
            ("Hotspot", self._format_number(row["hotspot_score"])),
            ("Ownership entropy", self._format_number(row["ownership_entropy"])),
            ("Recent change risk", self._format_number(row["recent_change_risk"])),
            ("Coverage gap", self._format_number(row["coverage_gap"])),
            ("Risk score", self._format_number(row["risk_score"])),
        ]
        body = [
            self._page_title(f"File Detail: {row['path']}"),
            self._render_nav("", repository_id),
            self._section("Summary", self._render_definition_list(details)),
            self._section(
                "Latest Metrics",
                self._render_table(
                    ("Measured At", "Covered", "Total", "Uncovered Ratio"),
                    [
                        {
                            "measured_at": row["measured_at"],
                            "covered_lines": row["covered_lines"],
                            "total_lines": row["total_lines"],
                            "uncovered_ratio": row["uncovered_ratio"],
                        }
                    ]
                    if row["measured_at"] is not None
                    else [],
                )
                if row["measured_at"] is not None
                else self._empty_state("No coverage snapshot recorded for this file."),
            ),
        ]
        return self._respond(
            start_response,
            "200 OK",
            "text/html; charset=utf-8",
            self._document(f"File Detail: {row['path']}", "".join(body)),
            head_only,
        )

    def _render_nav(self, active: str, repository_id: int | None = None) -> str:
        items = [
            ("home", "Home", "/"),
            ("risk", "Risk", "/risk"),
            ("hotspots", "Hotspots", "/hotspots"),
            ("ownership", "Ownership", "/ownership"),
        ]
        links = []
        for item_key, label, href in items:
            if repository_id is not None:
                href = href + "?" + urlencode({"repository_id": repository_id})
            class_name = "nav-link active" if item_key == active else "nav-link"
            links.append(f'<a class="{class_name}" href="{href}">{label}</a>')
        return f'<nav class="nav">{"".join(links)}</nav>'

    def _filter_banner(self, repository_id: int | None) -> str:
        if repository_id is None:
            return ""
        repository = self._fetch_one(
            """
            SELECT id, name, path
            FROM repositories
            WHERE id = ?
            """,
            (repository_id,),
        )
        if repository is None:
            return self._empty_state(f"Repository {repository_id} not found.")
        return (
            '<div class="empty-state">'
            f"Filtered to <strong>{html.escape(str(repository['name']))}</strong> "
            f"({html.escape(str(repository['path']))})."
            "</div>"
        )

    def _render_repository_list(
        self,
        repositories: list[sqlite3.Row],
        *,
        controls_html: str = "",
    ) -> str:
        if not repositories:
            return self._empty_state("No repositories have been ingested yet.")

        rows = []
        for repo in repositories:
            link = "/?" + urlencode({"repository_id": repo["id"]})
            rows.append(
                "<tr>"
                f"<td><a href=\"{link}\">{html.escape(str(repo['name']))}</a></td>"
                f"<td>{html.escape(str(repo['path']))}</td>"
                f"<td>{html.escape(str(repo['default_branch'] or ''))}</td>"
                f"<td>{html.escape(str(repo['created_at']))}</td>"
                f"<td><a href=\"{link}\">Open dashboard</a></td>"
                "</tr>"
            )
        controls_row = (
            f'<tr><th class="table-controls-cell" colspan="5">{controls_html}</th></tr>'
            if controls_html
            else ""
        )
        return (
            '<table class="table">'
            f"<thead>{controls_row}<tr><th>Name</th><th>Path</th>"
            "<th>Default Branch</th><th>Created</th><th>Action</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
        )

    def _repository_focus(self, repository: sqlite3.Row) -> str:
        repo_id = repository["id"]
        links = [
            ("Home", "/?" + urlencode({"repository_id": repo_id})),
            ("Risk", "/risk?" + urlencode({"repository_id": repo_id})),
            ("Hotspots", "/hotspots?" + urlencode({"repository_id": repo_id})),
            ("Ownership", "/ownership?" + urlencode({"repository_id": repo_id})),
        ]
        link_html = "".join(
            f'<a class="nav-link active" href="{href}">{label}</a>'
            for label, href in links
        )
        return (
            '<section class="panel">'
            "<h2>Selected Repository</h2>"
            f"<p><strong>{html.escape(str(repository['name']))}</strong>"
            f" <span style=\"color:var(--subtle)\">("
            f"{html.escape(str(repository['path']))})</span></p>"
            f'<div class="nav">{link_html}</div>'
            "<p style=\"color:var(--subtle);margin:0\">"
            "Start here: open the repository, then drill into risk, "
            "hotspots, or ownership."
            "</p>"
            "</section>"
        )

    def _table_controls(
        self,
        *,
        action: str,
        repository_id: int | None,
        search_name: str,
        search_value: str,
        search_placeholder: str,
        sort_name: str,
        sort_value: str,
        sort_options: tuple[tuple[str, str], ...],
        order_name: str,
        order_value: str,
    ) -> str:
        order_value = "asc" if order_value.lower() == "asc" else "desc"
        hidden_repo = (
            f'<input type="hidden" name="repository_id" value="{repository_id}" />'
            if repository_id is not None
            else ""
        )
        sort_options_html = []
        for value, label in sort_options:
            selected = " selected" if value == sort_value else ""
            sort_options_html.append(
                f'<option value="{html.escape(value)}"{selected}>'
                f"{html.escape(label)}</option>"
            )
        return (
            '<form class="filters" method="get" action="'
            f"{html.escape(action)}\">"
            f"{hidden_repo}"
            '<label><span>Filter</span>'
            f'<input type="search" name="{html.escape(search_name)}" '
            f'value="{html.escape(search_value)}" '
            f'placeholder="{html.escape(search_placeholder)}" />'
            "</label>"
            '<label><span>Sort</span>'
            f'<select name="{html.escape(sort_name)}">'
            f'{"".join(sort_options_html)}</select>'
            "</label>"
            '<label><span>Order</span>'
            f'<select name="{html.escape(order_name)}">'
            f'<option value="desc"'
            f'{" selected" if order_value == "desc" else ""}>Desc</option>'
            f'<option value="asc"'
            f'{" selected" if order_value == "asc" else ""}>Asc</option>'
            "</select>"
            "</label>"
            '<button type="submit">Apply</button>'
            "</form>"
        )

    def _render_table(
        self,
        headers: tuple[str, ...],
        rows: list[sqlite3.Row],
        *,
        controls_html: str = "",
        empty_message: str = "",
        preview: bool = False,
    ) -> str:
        body_rows = []
        for index, row in enumerate(rows, start=1):
            if headers == _HEADER_COLUMNS:
                path = html.escape(str(row["path"]))
                link = "/file?" + urlencode(
                    {"repository_id": row["repository_id"], "path": row["path"]}
                )
                body_rows.append(
                    "<tr>"
                    f"<td>{index}</td>"
                    f"<td><a href=\"{link}\">{path}</a></td>"
                    f"<td>{self._format_number(row['risk_score'])}</td>"
                    f"<td>{self._format_number(row['hotspot_score'])}</td>"
                    f"<td>{self._format_number(row['ownership_entropy'])}</td>"
                    f"<td>{self._format_number(row['recent_change_risk'])}</td>"
                    f"<td>{self._format_number(row['coverage_gap'])}</td>"
                    "</tr>"
                )
                continue

            if headers == (
                "Path",
                "Churn",
                "Insertions",
                "Deletions",
                "Commits",
                "Complexity",
                "Hotspot",
            ):
                path = html.escape(str(row["path"]))
                link = "/file?" + urlencode(
                    {"repository_id": row["repository_id"], "path": row["path"]}
                )
                body_rows.append(
                    "<tr>"
                    f"<td><a href=\"{link}\">{path}</a></td>"
                    f"<td>{self._format_number(row['churn'])}</td>"
                    f"<td>{self._format_number(row['insertions'])}</td>"
                    f"<td>{self._format_number(row['deletions'])}</td>"
                    f"<td>{self._format_number(row['commits_touched'])}</td>"
                    f"<td>{self._format_number(row['complexity'])}</td>"
                    f"<td>{self._format_number(row['hotspot_score'])}</td>"
                    "</tr>"
                )
                continue

            if headers == (
                "Path",
                "Total Contribution",
                "Authors",
                "Entropy",
            ):
                path = html.escape(str(row["path"]))
                link = "/file?" + urlencode(
                    {"repository_id": row["repository_id"], "path": row["path"]}
                )
                body_rows.append(
                    "<tr>"
                    f"<td><a href=\"{link}\">{path}</a></td>"
                    f"<td>{self._format_number(row['total_contribution'])}</td>"
                    f"<td>{self._format_number(row['contributing_authors'])}</td>"
                    f"<td>{self._format_number(row['ownership_entropy'])}</td>"
                    "</tr>"
                )
                continue

            if headers == (
                "Measured At",
                "Covered",
                "Total",
                "Uncovered Ratio",
            ):
                body_rows.append(
                    "<tr>"
                    f"<td>{html.escape(str(row['measured_at']))}</td>"
                    f"<td>{self._format_number(row['covered_lines'])}</td>"
                    f"<td>{self._format_number(row['total_lines'])}</td>"
                    f"<td>{self._format_number(row['uncovered_ratio'])}</td>"
                    "</tr>"
                )
                continue

        if not body_rows and empty_message:
            body_rows.append(
                f'<tr><td colspan="{len(headers)}" class="empty-state">'
                f"{html.escape(empty_message)}</td></tr>"
            )

        header_html = "".join(f"<th>{html.escape(column)}</th>" for column in headers)
        controls_row = (
            f'<tr><th class="table-controls-cell" colspan="{len(headers)}">'
            f"{controls_html}</th></tr>"
            if controls_html
            else ""
        )
        return (
            '<table class="table">'
            f"<thead>{controls_row}<tr>{header_html}</tr></thead>"
            f"<tbody>{''.join(body_rows)}</tbody>"
            "</table>"
        )

    def _render_definition_list(self, pairs: list[tuple[str, Any]]) -> str:
        items = []
        for label, value in pairs:
            items.append(
                f"<dt>{html.escape(str(label))}</dt><dd>{html.escape(str(value))}</dd>"
            )
        return f'<dl class="definition-list">{"".join(items)}</dl>'

    def _metric_guide(self) -> str:
        rows = [
            (
                "Risk score",
                "Overall ranking signal. Combines hotspot pressure, "
                "ownership spread, recent churn, and coverage gap.",
                "Higher is worse and should move to the top of the queue.",
                "Compare within the same repository; the absolute number "
                "is less important than rank.",
            ),
            (
                "Hotspot score",
                "Churn multiplied by complexity. High-churn complicated "
                "files deserve extra review.",
                "Higher is worse. A zero usually means no churn or missing metrics.",
                "Good: low relative to other files in the repo. Bad: "
                "top-decile files with sustained churn.",
            ),
            (
                "Ownership entropy",
                "How spread out the contribution history is across authors.",
                "Low means one or two authors dominate. High means more "
                "contributors and more coordination.",
                "Good for bus factor: moderate and stable. Bad if it is "
                "high on a risky file or paired with churn.",
            ),
            (
                "Recent change risk",
                "Recency-weighted churn. Recent edits matter more than old history.",
                "Higher is worse and signals a file that is still actively moving.",
                "Good: near zero or clearly below other files. Bad: "
                "repeatedly edited in the last 30-90 days.",
            ),
            (
                "Coverage gap",
                "Hotspot score multiplied by uncovered ratio. It highlights "
                "risky files that lack tests.",
                "Higher is worse; zero means either good coverage or "
                "low hotspot pressure.",
                "Good: zero or close to zero. Bad: high hotspot score with "
                "low coverage.",
            ),
        ]
        body_rows = []
        for metric, why, read, range_note in rows:
            body_rows.append(
                "<tr>"
                f"<td><strong>{html.escape(metric)}</strong></td>"
                f"<td>{html.escape(why)}</td>"
                f"<td>{html.escape(read)}</td>"
                f"<td>{html.escape(range_note)}</td>"
                "</tr>"
            )
        return (
            '<table class="table">'
            "<thead><tr><th>Metric</th><th>Why it matters</th>"
            "<th>How to read it</th><th>Good / Bad ranges</th></tr></thead>"
            f"<tbody>{''.join(body_rows)}</tbody>"
            "</table>"
        )

    def _card_grid(self, cards: list[tuple[str, Any]]) -> str:
        items = []
        for label, value in cards:
            items.append(
                '<section class="card">'
                f'<div class="card-label">{html.escape(str(label))}</div>'
                f'<div class="card-value">{html.escape(str(value))}</div>'
                "</section>"
            )
        return f'<div class="card-grid">{"".join(items)}</div>'

    def _summary_line(self, cards: list[tuple[str, Any]]) -> str:
        items = []
        for label, value in cards:
            items.append(
                '<span class="summary-pill">'
                f'<span class="summary-label">{html.escape(str(label))}</span>'
                f'<span class="summary-value">{html.escape(str(value))}</span>'
                "</span>"
            )
        return f'<div class="summary-line">{"".join(items)}</div>'

    def _section(self, title: str, content: str) -> str:
        return (
            '<section class="panel">'
            f"<h2>{html.escape(title)}</h2>"
            f"{content}"
            "</section>"
        )

    def _page_title(self, title: str) -> str:
        return (
            '<header class="hero">'
            f"<p class=\"eyebrow\">Codeanalysis</p>"
            f"<h1>{html.escape(title)}</h1>"
            "<p class=\"subtitle\">Local-first analytics for codebases."
            " Inspect risk, hotspots, ownership, and file detail from SQLite.</p>"
            "</header>"
        )

    def _empty_state(self, message: str) -> str:
        return f'<div class="empty-state">{html.escape(message)}</div>'

    def _document(self, title: str, body: str) -> str:
        return (
            "<!doctype html>"
            "<html lang=\"en\">"
            "<head>"
            '<meta charset="utf-8" />'
            '<meta name="viewport" content="width=device-width, initial-scale=1" />'
            f"<title>{html.escape(title)}</title>"
            f'<link rel="icon" href="{self._favicon_href()}" />'
            "<style>"
            ":root{--bg:#0b1020;--panel:#11182d;--panel-alt:#0f172a;--text:#eef2ff;"
            "--muted:#a5b4fc;--subtle:#94a3b8;--line:rgba(255,255,255,.08);"
            "--accent:#7c3aed;--accent-2:#22c55e;--warn:#f59e0b;}"
            "*{box-sizing:border-box}"
            "body{margin:0;font-family:Avenir Next,Avenir,Trebuchet MS,sans-serif;"
            "background:radial-gradient(circle at top left,#1d1b4b 0,#0b1020 38%,"
            "#050816 100%);color:var(--text);min-height:100vh}"
            "a{color:#c4b5fd;text-decoration:none}"
            "a:hover{text-decoration:underline}"
            ".shell{max-width:1200px;margin:0 auto;padding:24px}"
            ".hero{padding:24px 0 8px}"
            ".eyebrow{margin:0 0 8px;text-transform:uppercase;letter-spacing:.18em;"
            "font-size:.72rem;color:var(--muted)}"
            ".hero h1{margin:0;font-size:clamp(2rem,4vw,3.5rem);line-height:1.05}"
            ".subtitle{max-width:72ch;color:var(--subtle);font-size:1rem;line-height:1.6}"
            ".nav{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0 26px}"
            ".nav-link{padding:10px 14px;border:1px solid var(--line);"
            "border-radius:999px;background:rgba(255,255,255,.03)}"
            ".nav-link.active{background:linear-gradient(135deg,var(--accent),#4f46e5);"
            "color:white;border-color:transparent}"
            ".card-grid{display:grid;grid-template-columns:repeat(auto-fit,"
            "minmax(160px,1fr));gap:14px;margin:20px 0}"
            ".card,.panel,.empty-state{background:rgba(17,24,45,.85);"
            "backdrop-filter:blur(16px);border:1px solid var(--line);"
            "border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,.22)}"
            ".card{padding:18px 18px 16px}"
            ".card-label{font-size:.78rem;color:var(--subtle);"
            "text-transform:uppercase;letter-spacing:.12em}"
            ".card-value{margin-top:10px;font-size:1.8rem;font-weight:700}"
            ".summary-line{display:flex;flex-wrap:wrap;gap:10px;"
            "align-items:center;margin:18px 0 8px;padding:12px 14px;"
            "border:1px solid var(--line);border-radius:16px;"
            "background:rgba(255,255,255,.03)}"
            ".summary-pill{display:inline-flex;align-items:baseline;gap:8px;"
            "padding:8px 12px;border-radius:999px;background:rgba(255,255,255,.04);"
            "border:1px solid var(--line)}"
            ".summary-label{font-size:.72rem;text-transform:uppercase;"
            "letter-spacing:.1em;color:var(--muted)}"
            ".summary-value{font-size:1rem;font-weight:700;color:var(--text)}"
            ".panel{padding:20px;margin:18px 0}"
            ".panel h2{margin:0 0 14px;font-size:1.2rem}"
            ".table{width:100%;border-collapse:collapse;overflow:hidden}"
            ".table-controls-cell{padding:12px 10px 14px;"
            "background:rgba(255,255,255,.02)}"
            ".filters{display:grid;grid-template-columns:minmax(180px,2fr)"
            " repeat(2,minmax(120px,1fr)) auto;gap:10px;align-items:end;"
            "margin:0}"
            ".filters label{display:flex;flex-direction:column;gap:6px}"
            ".filters span{font-size:.72rem;color:var(--muted);"
            "text-transform:uppercase;letter-spacing:.1em}"
            ".filters input,.filters select{width:100%;padding:10px 12px;"
            "border:1px solid var(--line);border-radius:12px;"
            "background:rgba(255,255,255,.03);color:var(--text)}"
            ".filters button{padding:10px 14px;border:1px solid transparent;"
            "border-radius:12px;background:linear-gradient(135deg,var(--accent),#4f46e5);"
            "color:white;font-weight:600;cursor:pointer}"
            ".filters button:hover{filter:brightness(1.05)}"
            ".table th,.table td{padding:12px 10px;border-bottom:1px solid var(--line);"
            "text-align:left;vertical-align:top}"
            ".table th{font-size:.78rem;text-transform:uppercase;"
            "letter-spacing:.1em;color:var(--muted)}"
            ".table tbody tr:hover{background:rgba(255,255,255,.03)}"
            ".empty-state{padding:18px;color:var(--subtle)}"
            ".definition-list{display:grid;grid-template-columns:repeat(auto-fit,"
            "minmax(220px,1fr));gap:12px 18px;margin:0}"
            ".definition-list dt{font-size:.78rem;color:var(--muted);"
            "text-transform:uppercase;letter-spacing:.1em}"
            ".definition-list dd{margin:6px 0 0;font-size:1rem}"
            "@media (max-width:760px){.filters{grid-template-columns:1fr}}"
            "@media (max-width:640px){.shell{padding:18px}.table{display:block;"
            "overflow-x:auto}}"
            "</style>"
            "</head>"
            "<body><main class=\"shell\">"
            f"{body}"
            "</main></body></html>"
        )

    @staticmethod
    def _favicon_href() -> str:
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            '<defs><linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">'
            '<stop offset="0%" stop-color="#7c3aed"/>'
            '<stop offset="100%" stop-color="#22c55e"/>'
            "</linearGradient></defs>"
            '<rect width="64" height="64" rx="16" fill="#0b1020"/>'
            '<path d="M18 46L28 18h8l10 28h-7l-2-6H27l-2 6z" fill="url(#g)"/>'
            '<circle cx="43" cy="22" r="4" fill="#f59e0b"/>'
            "</svg>"
        )
        return "data:image/svg+xml;charset=utf-8," + quote(svg)

    def _respond(
        self,
        start_response: Any,
        status: str,
        content_type: str,
        text: str,
        head_only: bool,
        *,
        headers: list[tuple[str, str]] | None = None,
    ) -> list[bytes]:
        response_headers = [("Content-Type", content_type)]
        if headers:
            response_headers.extend(headers)
        body = text.encode("utf-8")
        response_headers.append(("Content-Length", str(len(body))))
        start_response(status, response_headers)
        return [] if head_only else [body]

    def _fetch_rows(
        self,
        query: str,
        parameters: tuple[Any, ...] = (),
    ) -> list[sqlite3.Row]:
        return self._connection.execute(query, parameters).fetchall()

    def _fetch_one(
        self,
        query: str,
        parameters: tuple[Any, ...] = (),
    ) -> sqlite3.Row | None:
        return self._connection.execute(query, parameters).fetchone()

    @staticmethod
    def _format_number(value: Any) -> str:
        if value is None:
            return "Unknown"
        if isinstance(value, float):
            return f"{value:.3f}".rstrip("0").rstrip(".")
        return str(value)

    @staticmethod
    def _parse_int(value: str) -> int | None:
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    @staticmethod
    def _normalize_order(value: str) -> str:
        return "ASC" if value.lower() == "asc" else "DESC"

    @staticmethod
    def _normalize_sort(
        value: str,
        allowed: dict[str, str],
        default: str,
    ) -> str:
        return allowed.get(value, allowed[default])

    def _repository_rows(
        self,
        search_query: str,
        sort_key: str,
        order_value: str,
    ) -> list[sqlite3.Row]:
        sort_expr = self._normalize_sort(
            sort_key,
            {
                "created_at": "created_at",
                "name": "name",
                "path": "path",
            },
            "created_at",
        )
        order_sql = self._normalize_order(order_value)
        parameters: list[Any] = []
        where_sql = ""
        if search_query:
            where_sql = "WHERE name LIKE ? OR path LIKE ?"
            like = f"%{search_query}%"
            parameters.extend([like, like])
        return self._fetch_rows(
            f"""
            SELECT id, name, path, default_branch, created_at
            FROM repositories
            {where_sql}
            ORDER BY {sort_expr} {order_sql}, id DESC
            """,
            tuple(parameters),
        )

    def _risk_rows(
        self,
        repository_id: int | None,
        search_query: str,
        sort_key: str,
        order_value: str,
        *,
        limit: int | None = None,
    ) -> list[sqlite3.Row]:
        return self._score_rows(
            """
            SELECT repository_id, file_id, path, risk_score, hotspot_score,
                   ownership_entropy, recent_change_risk, uncovered_ratio,
                   coverage_gap
            FROM risk_leaderboard
            """,
            {
                "risk_score": "risk_score",
                "hotspot_score": "hotspot_score",
                "ownership_entropy": "ownership_entropy",
                "recent_change_risk": "recent_change_risk",
                "coverage_gap": "coverage_gap",
                "path": "path",
            },
            "risk_score",
            repository_id,
            search_query,
            sort_key,
            order_value,
            limit=limit,
        )

    def _hotspot_rows(
        self,
        repository_id: int | None,
        search_query: str,
        sort_key: str,
        order_value: str,
    ) -> list[sqlite3.Row]:
        return self._score_rows(
            """
            SELECT repository_id, file_id, path, churn, insertions, deletions,
                   commits_touched, complexity, hotspot_score
            FROM hotspots
            """,
            {
                "hotspot_score": "hotspot_score",
                "churn": "churn",
                "complexity": "complexity",
                "path": "path",
            },
            "hotspot_score",
            repository_id,
            search_query,
            sort_key,
            order_value,
        )

    def _ownership_rows(
        self,
        repository_id: int | None,
        search_query: str,
        sort_key: str,
        order_value: str,
    ) -> list[sqlite3.Row]:
        return self._score_rows(
            """
            SELECT repository_id, file_id, path, total_contribution,
                   contributing_authors, ownership_entropy
            FROM ownership_entropy
            """,
            {
                "ownership_entropy": "ownership_entropy",
                "total_contribution": "total_contribution",
                "contributing_authors": "contributing_authors",
                "path": "path",
            },
            "ownership_entropy",
            repository_id,
            search_query,
            sort_key,
            order_value,
        )

    def _score_rows(
        self,
        select_sql: str,
        sort_map: dict[str, str],
        default_sort: str,
        repository_id: int | None,
        search_query: str,
        sort_key: str,
        order_value: str,
        *,
        limit: int | None = None,
    ) -> list[sqlite3.Row]:
        clauses = []
        parameters: list[Any] = []
        if repository_id is not None:
            clauses.append("repository_id = ?")
            parameters.append(repository_id)
        if search_query:
            clauses.append("path LIKE ?")
            parameters.append(f"%{search_query}%")
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sort_expr = self._normalize_sort(sort_key, sort_map, default_sort)
        order_sql = self._normalize_order(order_value)
        limit_sql = f" LIMIT {limit}" if limit is not None else ""
        return self._fetch_rows(
            f"""
            {select_sql}
            {where_sql}
            ORDER BY {sort_expr} {order_sql}, path ASC
            {limit_sql}
            """,
            tuple(parameters),
        )


def create_dashboard_app(connection: sqlite3.Connection) -> DashboardApplication:
    return DashboardApplication(connection)


def serve_dashboard(
    db_path: str | Path | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
) -> None:
    db_path = default_db_path() if db_path is None else db_path
    host = default_dashboard_host() if host is None else host
    port = default_dashboard_port() if port is None else port
    with closing(connect_database(db_path)) as connection:
        apply_migrations(connection)
        app = create_dashboard_app(connection)
        server = make_server(host, port, app)
        try:
            print(f"Serving dashboard on http://{host}:{port}")
            server.serve_forever()
        finally:
            server.server_close()
