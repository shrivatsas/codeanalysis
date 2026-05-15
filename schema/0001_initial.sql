CREATE TABLE repositories (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  path TEXT NOT NULL UNIQUE,
  default_branch TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE commits (
  id INTEGER PRIMARY KEY,
  repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  commit_hash TEXT NOT NULL,
  author_name TEXT NOT NULL,
  author_email TEXT,
  committed_at TEXT NOT NULL,
  message TEXT NOT NULL,
  insertions INTEGER NOT NULL DEFAULT 0 CHECK (insertions >= 0),
  deletions INTEGER NOT NULL DEFAULT 0 CHECK (deletions >= 0),
  files_changed INTEGER NOT NULL DEFAULT 0 CHECK (files_changed >= 0),
  UNIQUE(repository_id, commit_hash)
);

CREATE INDEX idx_commits_repository_committed_at
  ON commits(repository_id, committed_at);

CREATE TABLE files (
  id INTEGER PRIMARY KEY,
  repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  path TEXT NOT NULL,
  language TEXT,
  current_size_bytes INTEGER CHECK (current_size_bytes IS NULL OR current_size_bytes >= 0),
  is_deleted INTEGER NOT NULL DEFAULT 0 CHECK (is_deleted IN (0, 1)),
  UNIQUE(repository_id, path)
);

CREATE INDEX idx_files_repository_path
  ON files(repository_id, path);

CREATE TABLE commit_files (
  commit_id INTEGER NOT NULL REFERENCES commits(id) ON DELETE CASCADE,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  change_type TEXT NOT NULL CHECK (
    change_type IN ('added', 'modified', 'deleted', 'renamed', 'copied', 'unknown')
  ),
  old_path TEXT,
  insertions INTEGER NOT NULL DEFAULT 0 CHECK (insertions >= 0),
  deletions INTEGER NOT NULL DEFAULT 0 CHECK (deletions >= 0),
  PRIMARY KEY(commit_id, file_id)
);

CREATE INDEX idx_commit_files_file_id
  ON commit_files(file_id);

CREATE TABLE metrics_snapshot (
  id INTEGER PRIMARY KEY,
  repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  measured_at TEXT NOT NULL,
  loc INTEGER CHECK (loc IS NULL OR loc >= 0),
  complexity REAL CHECK (complexity IS NULL OR complexity >= 0),
  duplication REAL CHECK (duplication IS NULL OR duplication >= 0),
  fan_in INTEGER CHECK (fan_in IS NULL OR fan_in >= 0),
  fan_out INTEGER CHECK (fan_out IS NULL OR fan_out >= 0)
);

CREATE INDEX idx_metrics_snapshot_file_measured_at
  ON metrics_snapshot(file_id, measured_at DESC);

CREATE TABLE analysis_runs (
  id INTEGER PRIMARY KEY,
  repository_id INTEGER REFERENCES repositories(id) ON DELETE SET NULL,
  run_type TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('started', 'succeeded', 'failed')),
  started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT,
  message TEXT
);

CREATE INDEX idx_analysis_runs_repository_started_at
  ON analysis_runs(repository_id, started_at DESC);

CREATE VIEW file_churn AS
SELECT
  f.repository_id,
  f.id AS file_id,
  f.path,
  COALESCE(SUM(cf.insertions + cf.deletions), 0) AS churn,
  COALESCE(SUM(cf.insertions), 0) AS insertions,
  COALESCE(SUM(cf.deletions), 0) AS deletions,
  COUNT(DISTINCT cf.commit_id) AS commits_touched
FROM files AS f
LEFT JOIN commit_files AS cf ON cf.file_id = f.id
GROUP BY f.repository_id, f.id, f.path;

CREATE VIEW latest_file_metrics AS
SELECT
  ms.repository_id,
  ms.file_id,
  f.path,
  ms.measured_at,
  ms.loc,
  ms.complexity,
  ms.duplication,
  ms.fan_in,
  ms.fan_out
FROM metrics_snapshot AS ms
JOIN files AS f ON f.id = ms.file_id
WHERE NOT EXISTS (
  SELECT 1
  FROM metrics_snapshot AS newer
  WHERE newer.file_id = ms.file_id
    AND (
      newer.measured_at > ms.measured_at
      OR (newer.measured_at = ms.measured_at AND newer.id > ms.id)
    )
);

CREATE VIEW hotspots AS
SELECT
  fc.repository_id,
  fc.file_id,
  fc.path,
  fc.churn,
  fc.insertions,
  fc.deletions,
  fc.commits_touched,
  COALESCE(lfm.complexity, 0) AS complexity,
  fc.churn * COALESCE(lfm.complexity, 0) AS hotspot_score
FROM file_churn AS fc
LEFT JOIN latest_file_metrics AS lfm ON lfm.file_id = fc.file_id;
