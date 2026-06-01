from __future__ import annotations

from contextlib import closing

from src.analytics.database import apply_migrations, connect_database


def test_ownership_entropy_view_uses_author_distribution() -> None:
    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        apply_migrations(connection)
        repository_id, file_id = _insert_repository_and_file(connection)
        first_commit = _insert_commit(
            connection,
            repository_id,
            "ada",
            "2026-01-01T00:00:00Z",
        )
        second_commit = _insert_commit(
            connection,
            repository_id,
            "bob",
            "2026-05-01T00:00:00Z",
        )
        _insert_commit_file(connection, first_commit, file_id, 5, 0)
        _insert_commit_file(connection, second_commit, file_id, 5, 0)

        entropy = connection.execute(
            """
            SELECT total_contribution, contributing_authors, ownership_entropy
            FROM ownership_entropy
            WHERE file_id = ?
            """,
            (file_id,),
        ).fetchone()

    assert dict(entropy) == {
        "total_contribution": 10,
        "contributing_authors": 2,
        "ownership_entropy": 0.6931471805599453,
    }


def test_recent_change_risk_uses_recency_buckets() -> None:
    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        apply_migrations(connection)
        repository_id, file_id = _insert_repository_and_file(connection)
        old_commit = _insert_commit(
            connection,
            repository_id,
            "ada",
            "2026-01-01T00:00:00Z",
        )
        latest_commit = _insert_commit(
            connection,
            repository_id,
            "bob",
            "2026-05-01T00:00:00Z",
        )
        _insert_commit_file(connection, old_commit, file_id, 5, 0)
        _insert_commit_file(connection, latest_commit, file_id, 5, 0)

        risk = connection.execute(
            """
            SELECT recent_change_risk
            FROM recent_change_risk
            WHERE file_id = ?
            """,
            (file_id,),
        ).fetchone()["recent_change_risk"]

    assert risk == 6.25


def test_risk_leaderboard_combines_scores_and_coverage_gap() -> None:
    with closing(connect_database(":memory:", enable_wal=False)) as connection:
        apply_migrations(connection)
        repository_id = _insert_repository(connection)
        high_file = _insert_file(connection, repository_id, "app.py")
        low_file = _insert_file(connection, repository_id, "lib.py")

        high_old = _insert_commit(
            connection,
            repository_id,
            "ada",
            "2026-01-01T00:00:00Z",
        )
        high_latest = _insert_commit(
            connection,
            repository_id,
            "bob",
            "2026-05-01T00:00:00Z",
        )
        _insert_commit_file(connection, high_old, high_file, 5, 0)
        _insert_commit_file(connection, high_latest, high_file, 5, 0)
        _insert_snapshot(connection, repository_id, high_file, 2.0, 100)
        _insert_coverage(connection, repository_id, high_file, 25, 100)

        low_commit = _insert_commit(
            connection,
            repository_id,
            "ada",
            "2026-05-01T00:00:00Z",
        )
        _insert_commit_file(connection, low_commit, low_file, 2, 0)
        _insert_snapshot(connection, repository_id, low_file, 1.0, 20)
        _insert_coverage(connection, repository_id, low_file, 20, 20)

        rows = connection.execute(
            """
            SELECT path, hotspot_score, ownership_entropy, recent_change_risk,
                   uncovered_ratio, coverage_gap, risk_score
            FROM risk_leaderboard
            ORDER BY risk_score DESC, path ASC
            """
        ).fetchall()

    assert len(rows) == 2
    assert dict(rows[0]) == {
        "path": "app.py",
        "hotspot_score": 20.0,
        "ownership_entropy": 0.6931471805599453,
        "recent_change_risk": 6.25,
        "uncovered_ratio": 0.75,
        "coverage_gap": 15.0,
        "risk_score": 41.94314718055995,
    }
    assert dict(rows[1]) == {
        "path": "lib.py",
        "hotspot_score": 2.0,
        "ownership_entropy": 0.0,
        "recent_change_risk": 2.0,
        "uncovered_ratio": 0.0,
        "coverage_gap": 0.0,
        "risk_score": 4.0,
    }


def _insert_repository(connection):
    return connection.execute(
        """
        INSERT INTO repositories (name, path, default_branch)
        VALUES ('repo', '/tmp/repo', 'main')
        RETURNING id
        """
    ).fetchone()["id"]


def _insert_repository_and_file(connection):
    repository_id = _insert_repository(connection)
    file_id = _insert_file(connection, repository_id, "app.py")
    return repository_id, file_id


def _insert_file(connection, repository_id, path):
    return connection.execute(
        """
        INSERT INTO files (repository_id, path, language)
        VALUES (?, ?, 'Python')
        RETURNING id
        """,
        (repository_id, path),
    ).fetchone()["id"]


def _insert_commit(connection, repository_id, author_name, committed_at):
    return connection.execute(
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
        VALUES (?, ?, ?, ?, 'msg', 0, 0, 1)
        RETURNING id
        """,
        (repository_id, f"{author_name}-{committed_at}", author_name, committed_at),
    ).fetchone()["id"]


def _insert_commit_file(connection, commit_id, file_id, insertions, deletions):
    connection.execute(
        """
        INSERT INTO commit_files (
          commit_id,
          file_id,
          change_type,
          insertions,
          deletions
        )
        VALUES (?, ?, 'modified', ?, ?)
        """,
        (commit_id, file_id, insertions, deletions),
    )


def _insert_snapshot(connection, repository_id, file_id, complexity, loc):
    connection.execute(
        """
        INSERT INTO metrics_snapshot (
          repository_id,
          file_id,
          measured_at,
          loc,
          complexity
        )
        VALUES (?, ?, '2026-05-01T00:00:00Z', ?, ?)
        """,
        (repository_id, file_id, loc, complexity),
    )


def _insert_coverage(connection, repository_id, file_id, covered_lines, total_lines):
    connection.execute(
        """
        INSERT INTO coverage_by_file (
          repository_id,
          file_id,
          measured_at,
          covered_lines,
          total_lines
        )
        VALUES (?, ?, '2026-05-01T00:00:00Z', ?, ?)
        """,
        (repository_id, file_id, covered_lines, total_lines),
    )
