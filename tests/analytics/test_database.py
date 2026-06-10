import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from src.analytics.database import apply_migrations, connect_database


def test_apply_migrations_creates_initial_schema() -> None:
    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        applied = apply_migrations(connection)

        assert applied == [
            "0001_initial.sql",
            "0002_risk_scoring.sql",
            "0003_ci_cd.sql",
        ]
        tables = {row["name"] for row in connection.execute("""
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """)}

    assert {
        "schema_migrations",
        "repositories",
        "commits",
        "files",
        "commit_files",
        "metrics_snapshot",
        "analysis_runs",
        "coverage_by_file",
        "pipeline_runs",
        "job_runs",
        "test_results",
    }.issubset(tables)


def test_apply_migrations_is_idempotent() -> None:
    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        assert apply_migrations(connection) == [
            "0001_initial.sql",
            "0002_risk_scoring.sql",
            "0003_ci_cd.sql",
        ]
        assert apply_migrations(connection) == []

        migration_count = connection.execute(
            "SELECT COUNT(*) AS count FROM schema_migrations"
        ).fetchone()["count"]

    assert migration_count == 3


def test_apply_migrations_rejects_changed_migration(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "schema"
    migrations_dir.mkdir()
    migration = migrations_dir / "0001_test.sql"
    migration.write_text(
        "CREATE TABLE sample (id INTEGER PRIMARY KEY);",
        encoding="utf-8",
    )

    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        apply_migrations(connection, migrations_dir)
        migration.write_text(
            "CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT);",
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="has changed"):
            apply_migrations(connection, migrations_dir)


def test_connect_database_enforces_foreign_keys() -> None:
    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        apply_migrations(connection)

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("""
                INSERT INTO commits (
                  repository_id,
                  commit_hash,
                  author_name,
                  committed_at,
                  message
                )
                VALUES (999, 'abc123', 'Ada', '2026-05-15T00:00:00Z', 'Test')
                """)


def test_core_views_compute_churn_and_hotspots() -> None:
    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        apply_migrations(connection)
        repository_id = connection.execute("""
            INSERT INTO repositories (name, path, default_branch)
            VALUES ('demo', '/tmp/demo', 'main')
            RETURNING id
            """).fetchone()["id"]
        commit_id = connection.execute(
            """
            INSERT INTO commits (
              repository_id,
              commit_hash,
              author_name,
              committed_at,
              message,
              insertions,
              deletions,
              files_changed
            )
            VALUES (?, 'abc123', 'Ada', '2026-05-15T00:00:00Z', 'Initial', 10, 4, 1)
            RETURNING id
            """,
            (repository_id,),
        ).fetchone()["id"]
        file_id = connection.execute(
            """
            INSERT INTO files (repository_id, path, language)
            VALUES (?, 'src/app.py', 'Python')
            RETURNING id
            """,
            (repository_id,),
        ).fetchone()["id"]
        connection.execute(
            """
            INSERT INTO commit_files (
              commit_id,
              file_id,
              change_type,
              insertions,
              deletions
            )
            VALUES (?, ?, 'modified', 10, 4)
            """,
            (commit_id, file_id),
        )
        connection.execute(
            """
            INSERT INTO metrics_snapshot (
              repository_id,
              file_id,
              measured_at,
              loc,
              complexity
            )
            VALUES (?, ?, '2026-05-15T00:00:00Z', 100, 2.5)
            """,
            (repository_id, file_id),
        )

        hotspot = connection.execute(
            """
            SELECT path, churn, complexity, hotspot_score
            FROM hotspots
            WHERE file_id = ?
            """,
            (file_id,),
        ).fetchone()

    assert dict(hotspot) == {
        "path": "src/app.py",
        "churn": 14,
        "complexity": 2.5,
        "hotspot_score": 35.0,
    }
