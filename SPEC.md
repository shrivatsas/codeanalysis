# Spec: Local-First Codebase Analysis

## Overview
This project provides data-driven analysis for large software codebases while staying easy to run on a developer machine or a single cloud instance. It collects version control, static analysis, CI/CD, issue, and runtime signals, then turns them into local dashboards and ranked recommendations for engineering teams.

The default deployment is a single Python application backed by SQLite. Heavier components such as ClickHouse, Grafana, Metabase, or distributed workers are optional future adapters, not required infrastructure for the core product.

## Goals
- Identify high-risk and high-churn areas of a codebase.
- Detect architectural and ownership bottlenecks.
- Quantify engineering productivity, quality, and change impact.
- Provide visual dashboards that run locally or on one small server.
- Keep installation, persistence, backup, and operations simple.

## Non-Goals For The MVP
- Distributed ingestion or multi-node analytics.
- Mandatory managed services.
- Real-time streaming telemetry.
- Training production ML models before enough historical data exists.
- Requiring ClickHouse, Grafana, Metabase, or external BI tools.

## Deployment Model

### Local Developer Mode
- Run with `uv` and `task` commands.
- Store data in `data/codeanalysis.db` by default.
- Host dashboards on `127.0.0.1` with a local web server.
- Analyze one or more local Git repositories from the same machine.

### Single-Instance Cloud Mode
- Run the same app in one VM or one container.
- Persist SQLite on an attached volume.
- Configure paths and secrets through environment variables.
- Use WAL mode and periodic backups for operational safety.
- Scale vertically first before introducing external services.

### Optional Scale-Out Adapters
- ClickHouse can be introduced later for very large histories or multi-tenant deployments.
- Grafana or Metabase can be attached to exported tables or a replicated analytics database.
- Background workers can be added if ingestion jobs become too slow for the web process.

## Data Sources
| Source | MVP Priority | Description | Key Entities |
| --- | --- | --- | --- |
| Git | Required | Local version control history: commits, diffs, authors, timestamps | `repositories`, `commits`, `files`, `commit_files` |
| Static Analysis | Required | File size, language, complexity, duplication, dependency edges | `metrics_snapshot`, `dependencies` |
| CI/CD | Optional | Build, test, and deployment pipeline summaries | `pipeline_runs`, `job_runs`, `test_results` |
| Issue Tracker | Optional | Bugs, incidents, linked PRs, affected components | `issues`, `incidents`, `components` |
| Runtime Telemetry | Optional | Coverage and performance summaries imported from files | `traces`, `coverage_by_file` |

## Analytic Dimensions

### Version Control Analytics
- **Collected**: Commit metadata, diffs, authorship, timestamps.
- **Techniques**: Hotspot analysis, temporal coupling, ownership entropy, lead time, batch size, defect correlation, review dynamics where review data is available.

### Static Code Analysis
- **Collected**: LOC, file size, language, cyclomatic complexity, duplication percentage, dependency edges.
- **Techniques**: Complexity-versus-churn analysis, dependency graph clustering, instability metrics, clone detection, API surface change tracking.

### Test & Runtime Analysis
- **Collected**: Coverage, mutation score, runtime profiles.
- **Techniques**: Overlay coverage with hotspots, detect flaky tests, compute mutation score, aggregate traces to identify slow paths.

### CI/CD Pipeline Analysis
- **Collected**: Build times, cache hits, failure reasons.
- **Techniques**: Anomaly detection on build time, deployment throughput, change-failure rate, job-duration ranking.

### Issue & Incident Analytics
- **Collected**: Linked commits, affected components, severity, resolution time.
- **Techniques**: Incident density by component, bug correlation with churn and ownership, MTTR by module.

### Semantic & ML-Based Analysis
- **Collected**: Commit messages, PR descriptions, docstrings, issue text.
- **Techniques**: Text similarity, topic discovery, semantic search, duplicate issue detection.
- **MVP stance**: Keep this optional until the deterministic analytics pipeline is useful.

### Socio-Technical Graphs
- **Collected**: Author-file relationships and review assignments where available.
- **Techniques**: Reviewer centrality, team alignment with dependency clusters, handoff metrics, collaboration density.

## Metrics & Dashboards
| Dashboard | MVP Visuals | Purpose |
| --- | --- | --- |
| Risk Leaderboard | Ranked table with filters | Prioritize testing, review, and refactoring |
| Hotspot Map | Table and treemap by churn x complexity | Identify refactor targets |
| File Detail | Time series and ownership summary | Explain why a file is risky |
| Ownership | Tile grid or table of primary/secondary owners | Expose silos and concentration risk |
| CI Health | Time series of durations and failures | Detect delivery regressions |
| Change Funnel | Commit -> review -> deploy -> incident summary | Observe delivery health |

## MVP Architecture

### Runtime Components
- Python 3.11 application.
- SQLite database with WAL mode.
- SQL migrations stored in `schema/`.
- CLI commands in `src/cli/`.
- Analytics modules in `src/analytics/`.
- Dashboard application in `src/dashboards/`.
- Config files in `configs/`, with deploy-time overrides from environment variables.

### Storage
- Default database path: `data/codeanalysis.db`.
- Use normalized tables for raw events and SQL views for derived metrics.
- Store time-series snapshots rather than only latest values.
- Keep generated extracts out of version control except tiny fixtures.
- Back up the SQLite database file after checkpointing WAL.

### Ingestion
- Start with local Git repositories.
- Use PyDriller or direct Git command parsing behind a small ingestion interface.
- Upsert records to make repeated ingestion idempotent.
- Record ingestion attempts in `analysis_runs`.
- Add API connectors later for GitHub, GitLab, CI systems, and issue trackers.

### Dashboard
- Prefer a lightweight Python web stack such as FastAPI with server-rendered templates.
- Use Plotly or simple HTML tables for early charts.
- Avoid requiring a separate BI server for the MVP.

## Initial SQLite Schema Direction
The first schema migration should create normalized tables and views similar to:

```sql
CREATE TABLE repositories (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  path TEXT NOT NULL UNIQUE,
  default_branch TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE commits (
  id INTEGER PRIMARY KEY,
  repository_id INTEGER NOT NULL REFERENCES repositories(id),
  commit_hash TEXT NOT NULL,
  author_name TEXT NOT NULL,
  author_email TEXT,
  committed_at TEXT NOT NULL,
  message TEXT NOT NULL,
  insertions INTEGER NOT NULL DEFAULT 0,
  deletions INTEGER NOT NULL DEFAULT 0,
  UNIQUE(repository_id, commit_hash)
);

CREATE TABLE files (
  id INTEGER PRIMARY KEY,
  repository_id INTEGER NOT NULL REFERENCES repositories(id),
  path TEXT NOT NULL,
  language TEXT,
  current_size_bytes INTEGER,
  UNIQUE(repository_id, path)
);

CREATE TABLE commit_files (
  commit_id INTEGER NOT NULL REFERENCES commits(id),
  file_id INTEGER NOT NULL REFERENCES files(id),
  change_type TEXT NOT NULL,
  insertions INTEGER NOT NULL DEFAULT 0,
  deletions INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(commit_id, file_id)
);

CREATE TABLE metrics_snapshot (
  id INTEGER PRIMARY KEY,
  repository_id INTEGER NOT NULL REFERENCES repositories(id),
  file_id INTEGER NOT NULL REFERENCES files(id),
  measured_at TEXT NOT NULL,
  loc INTEGER,
  complexity REAL,
  duplication REAL,
  fan_in INTEGER,
  fan_out INTEGER
);

CREATE VIEW file_churn AS
SELECT
  file_id,
  SUM(insertions + deletions) AS churn
FROM commit_files
GROUP BY file_id;
```

Follow-up migrations should add issue, CI, dependency, and runtime tables as those integrations are implemented.

## Modeling & Scoring
- Start with deterministic scoring:
  - `hotspot_score = churn * normalized_complexity`
  - `ownership_risk = entropy(author_contributions)`
  - `recent_change_risk = weighted_recent_churn`
  - `coverage_gap = hotspot_score * uncovered_ratio`
- Publish scores through SQL views or lightweight Python materialization.
- Add logistic regression or LightGBM later when defect labels and enough historical data exist.
- Keep model inputs inspectable so dashboard users can understand each score.

## Implementation Phases

### Phase 1: Local-First Spec
- Reframe the project around SQLite and single-instance hosting.
- Preserve ClickHouse and BI tools as future adapters.
- Define MVP boundaries and operational constraints.

### Phase 2: Project Skeleton
- Add Python project metadata.
- Create package directories for ingestion, analytics, modeling, dashboards, and CLI commands.
- Add schema, config, data, and test directories.
- Keep placeholder modules importable.

### Phase 3: SQLite Schema
- Add the first SQL migration.
- Add a database helper module.
- Add tests for schema creation and core views.

### Phase 4: Git Ingestion MVP
- Add a CLI command to ingest a local repository.
- Store commits, files, and commit-file changes in SQLite.
- Make ingestion idempotent.
- Test with a temporary Git repository fixture.

### Phase 5: Static Metrics MVP
- Collect LOC, language, file size, and basic complexity.
- Store repeatable snapshots in SQLite.
- Add focused tests for empty repositories and deleted files.

### Phase 6: Analytics And Risk Scoring
- Implement hotspot scoring, ownership entropy, and risk leaderboard queries.
- Add regression tests for edge cases.

### Phase 7: Local Dashboard
- Serve dashboards locally.
- Add pages for risk leaderboard, hotspots, ownership, and file detail.
- Add smoke tests for routes.

### Phase 8: Single-Instance Packaging
- Add Docker or documented `uv` deployment.
- Configure database path and host/port through environment variables.
- Document backup and restore.

## Use Cases
| Question | Technique |
| --- | --- |
| Where should we refactor first? | Hotspot analysis and temporal coupling |
| Why are builds slow? | CI duration ranking and anomaly detection |
| Why do bugs cluster in certain areas? | Churn x complexity x ownership correlation |
| Is our architecture modular? | Dependency clustering |
| Are we shipping faster safely? | Lead time, batch size, change-failure rate |

## Anti-Patterns & Pitfalls
- Avoid vanity metrics such as global coverage percentage without risk context.
- Avoid snapshot-only metrics; store historical snapshots for trend analysis.
- Avoid requiring heavy infrastructure before the core insights are proven.
- Account for people dynamics: review and ownership data are critical.
- Keep the feedback loop by tagging defects to components and commits.
- Treat SQLite as an operational database: use indexes, WAL mode, migrations, and backups.

## Deliverables
1. Local-first project skeleton and reproducible `uv` setup.
2. SQLite schema migrations and database helper module.
3. Git ingestion CLI for local repositories.
4. Static metrics collection and snapshot storage.
5. Risk scoring and analytics views.
6. Locally hosted dashboard.
7. Single-instance deployment documentation.

## Extensions
- GitHub/GitLab API ingestion.
- CI and issue tracker connectors.
- Embeddings-based semantic search over commits and code.
- LLM-assisted natural-language queries.
- Anomaly detection for sudden churn or ownership drops.
- ClickHouse adapter for very large or multi-tenant deployments.
