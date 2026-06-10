CREATE TABLE pipeline_runs (
  id INTEGER PRIMARY KEY,
  repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  pipeline_name TEXT NOT NULL,
  run_key TEXT NOT NULL,
  branch TEXT,
  commit_hash TEXT,
  status TEXT NOT NULL CHECK (
    status IN ('queued', 'running', 'passed', 'failed', 'canceled')
  ),
  started_at TEXT NOT NULL,
  finished_at TEXT,
  duration_seconds REAL CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
  UNIQUE(repository_id, pipeline_name, run_key)
);

CREATE INDEX idx_pipeline_runs_repository_started_at
  ON pipeline_runs(repository_id, started_at DESC);

CREATE TABLE job_runs (
  id INTEGER PRIMARY KEY,
  pipeline_run_id INTEGER NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
  job_name TEXT NOT NULL,
  status TEXT NOT NULL CHECK (
    status IN ('queued', 'running', 'passed', 'failed', 'canceled', 'skipped')
  ),
  started_at TEXT,
  finished_at TEXT,
  duration_seconds REAL CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
  failure_reason TEXT,
  UNIQUE(pipeline_run_id, job_name)
);

CREATE INDEX idx_job_runs_pipeline_status
  ON job_runs(pipeline_run_id, status);

CREATE TABLE test_results (
  id INTEGER PRIMARY KEY,
  job_run_id INTEGER NOT NULL REFERENCES job_runs(id) ON DELETE CASCADE,
  test_name TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('passed', 'failed', 'skipped')),
  started_at TEXT,
  finished_at TEXT,
  duration_seconds REAL CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
  failure_reason TEXT,
  UNIQUE(job_run_id, test_name)
);

CREATE INDEX idx_test_results_job_status
  ON test_results(job_run_id, status);

CREATE VIEW ci_pipeline_health AS
SELECT
  pr.repository_id,
  pr.pipeline_name,
  COUNT(*) AS total_runs,
  SUM(CASE WHEN pr.status = 'passed' THEN 1 ELSE 0 END) AS passed_runs,
  SUM(CASE WHEN pr.status = 'failed' THEN 1 ELSE 0 END) AS failed_runs,
  CASE
    WHEN COUNT(*) = 0 THEN 0.0
    ELSE SUM(CASE WHEN pr.status = 'failed' THEN 1 ELSE 0 END) * 1.0 / COUNT(*)
  END AS failure_rate,
  AVG(pr.duration_seconds) AS avg_duration_seconds,
  MAX(pr.finished_at) AS latest_finished_at
FROM pipeline_runs AS pr
GROUP BY pr.repository_id, pr.pipeline_name;
