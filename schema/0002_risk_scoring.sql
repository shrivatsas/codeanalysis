CREATE TABLE coverage_by_file (
  id INTEGER PRIMARY KEY,
  repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  measured_at TEXT NOT NULL,
  covered_lines INTEGER NOT NULL DEFAULT 0 CHECK (covered_lines >= 0),
  total_lines INTEGER NOT NULL DEFAULT 0 CHECK (total_lines >= 0),
  UNIQUE(repository_id, file_id, measured_at)
);

CREATE INDEX idx_coverage_by_file_file_measured_at
  ON coverage_by_file(file_id, measured_at DESC);

CREATE VIEW latest_coverage_by_file AS
SELECT
  cbf.repository_id,
  cbf.file_id,
  f.path,
  cbf.measured_at,
  cbf.covered_lines,
  cbf.total_lines,
  CASE
    WHEN cbf.total_lines = 0 THEN NULL
    ELSE 1.0 - (cbf.covered_lines * 1.0 / cbf.total_lines)
  END AS uncovered_ratio
FROM coverage_by_file AS cbf
JOIN files AS f ON f.id = cbf.file_id
WHERE NOT EXISTS (
  SELECT 1
  FROM coverage_by_file AS newer
  WHERE newer.file_id = cbf.file_id
    AND (
      newer.measured_at > cbf.measured_at
      OR (newer.measured_at = cbf.measured_at AND newer.id > cbf.id)
    )
);

CREATE VIEW ownership_entropy AS
WITH author_contributions AS (
  SELECT
    f.repository_id,
    cf.file_id,
    f.path,
    c.author_name,
    SUM(cf.insertions + cf.deletions) AS contribution
  FROM commit_files AS cf
  JOIN commits AS c ON c.id = cf.commit_id
  JOIN files AS f ON f.id = cf.file_id
  GROUP BY f.repository_id, cf.file_id, f.path, c.author_name
),
file_totals AS (
  SELECT
    repository_id,
    file_id,
    path,
    SUM(contribution) AS total_contribution
  FROM author_contributions
  GROUP BY repository_id, file_id, path
)
SELECT
  ac.repository_id,
  ac.file_id,
  ac.path,
  ft.total_contribution,
  COUNT(*) AS contributing_authors,
  CASE
    WHEN ft.total_contribution <= 0 THEN 0.0
    ELSE -SUM(
      CASE
        WHEN ac.contribution <= 0 THEN 0.0
        ELSE (
          (ac.contribution * 1.0 / ft.total_contribution)
          * ln(ac.contribution * 1.0 / ft.total_contribution)
        )
      END
    )
  END AS ownership_entropy
FROM author_contributions AS ac
JOIN file_totals AS ft ON ft.file_id = ac.file_id
GROUP BY ac.repository_id, ac.file_id, ac.path, ft.total_contribution;

CREATE VIEW recent_change_risk AS
WITH file_commit_history AS (
  SELECT
    f.repository_id,
    cf.file_id,
    f.path,
    c.committed_at,
    (cf.insertions + cf.deletions) AS churn,
    julianday(file_max.latest_committed_at) - julianday(c.committed_at) AS age_days
  FROM commit_files AS cf
  JOIN commits AS c ON c.id = cf.commit_id
  JOIN files AS f ON f.id = cf.file_id
  JOIN (
    SELECT
      cf2.file_id,
      MAX(c2.committed_at) AS latest_committed_at
    FROM commit_files AS cf2
    JOIN commits AS c2 ON c2.id = cf2.commit_id
    GROUP BY cf2.file_id
  ) AS file_max ON file_max.file_id = cf.file_id
)
SELECT
  repository_id,
  file_id,
  path,
  COALESCE(
    SUM(
      churn * CASE
        WHEN age_days <= 30 THEN 1.0
        WHEN age_days <= 90 THEN 0.5
        WHEN age_days <= 180 THEN 0.25
        ELSE 0.1
      END
    ),
    0.0
  ) AS recent_change_risk
FROM file_commit_history
GROUP BY repository_id, file_id, path;

CREATE VIEW coverage_gap AS
SELECT
  h.repository_id,
  h.file_id,
  h.path,
  h.hotspot_score,
  COALESCE(lcbf.uncovered_ratio, 0.0) AS uncovered_ratio,
  h.hotspot_score * COALESCE(lcbf.uncovered_ratio, 0.0) AS coverage_gap
FROM hotspots AS h
LEFT JOIN latest_coverage_by_file AS lcbf ON lcbf.file_id = h.file_id;

CREATE VIEW risk_leaderboard AS
SELECT
  h.repository_id,
  h.file_id,
  h.path,
  h.churn,
  h.complexity,
  h.hotspot_score,
  COALESCE(oe.ownership_entropy, 0.0) AS ownership_entropy,
  COALESCE(rc.recent_change_risk, 0.0) AS recent_change_risk,
  COALESCE(cg.uncovered_ratio, 0.0) AS uncovered_ratio,
  COALESCE(cg.coverage_gap, 0.0) AS coverage_gap,
  (
    h.hotspot_score
    + COALESCE(oe.ownership_entropy, 0.0)
    + COALESCE(rc.recent_change_risk, 0.0)
    + COALESCE(cg.coverage_gap, 0.0)
  ) AS risk_score
FROM hotspots AS h
LEFT JOIN ownership_entropy AS oe ON oe.file_id = h.file_id
LEFT JOIN recent_change_risk AS rc ON rc.file_id = h.file_id
LEFT JOIN coverage_gap AS cg ON cg.file_id = h.file_id;
