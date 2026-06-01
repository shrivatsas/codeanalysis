# Codeanalysis Phased Plan

## Current State

- Repository is on `main` and aligned with `origin/main` after the latest dashboard changes.
- Test suite is passing: `24 passed`, `90%` coverage.
- Implemented:
  - SQLite connection and migration helpers in `src/analytics/database.py`
  - Initial schema and analytics views in `schema/0001_initial.sql`
  - Risk scoring and leaderboard views in `schema/0002_risk_scoring.sql`
  - Local Git ingestion in `src/ingestion/git_loader.py`
  - CLI entrypoint for local repository ingestion in `src/cli/cmd_ingest_git.py`
  - Static file metrics collection in `src/analytics/static_metrics.py`
  - CLI entrypoint for static metrics collection in `src/cli/cmd_collect_metrics.py`
  - Schema validation entrypoint in `src/analytics/validators/__main__.py`
- Implemented dashboard application in `src/dashboards/` with:
  - repository selection on the home page
  - a compact counts summary line
  - risk, hotspot, ownership, and file detail views
  - table filtering and ordering controls
  - an inline favicon
- Implemented coverage artifact ingestion in `src/ingestion/coverage_loader.py`
  with a CLI entrypoint in `src/cli/cmd_ingest_coverage.py`
- Not yet implemented:
  - Packaging, deployment, and backup documentation
  - CI, issue, dependency, and runtime ingestion

## Phase 1: Stabilize The Core

### Goal
Lock down the current foundation so later work can build on it safely.

### Work Items
- Keep the SQLite-first architecture as the baseline.
- Preserve idempotent ingestion and migration checksum safety.
- Continue using `analysis_runs` as the audit trail for ingestion and future analytics jobs.
- Make the current CLI path the canonical ingestion entrypoint.

### Exit Criteria
- Migration application remains deterministic and repeatable.
- Git ingestion continues to be idempotent across repeated runs.
- The core schema and views continue to pass the existing test suite.

## Phase 2: Static Metrics MVP

### Goal
Populate repeatable file-level snapshots so risk and hotspot analysis can use real static data.

### Work Items
- Add a file metrics collector that walks repository contents and captures:
  - LOC
  - file size
  - language
  - a simple complexity input or placeholder that can be refined later
- Decide how snapshots are triggered:
  - run as a dedicated CLI command, or
  - run as a library function called from a future pipeline step
- Store each measurement as a new `metrics_snapshot` record with a timestamp.
- Mark deleted files explicitly so old snapshots remain understandable.
- Keep unchanged files from generating duplicate work unless the run is intended to resnapshot the repo.

### Tests
- Empty repository produces no snapshot rows and no crashes.
- Deleted files are handled without file-stat failures.
- Re-running on the same repository preserves idempotent expectations where appropriate.
- Snapshot rows are queryable through the existing latest-metrics view.

### Exit Criteria
- A repository can be scanned locally and produce `metrics_snapshot` rows.
- Snapshot data can be joined with files and fed into hotspot scoring.

## Phase 3: Analytics And Risk Scoring

### Goal
Turn raw churn and static metrics into explainable ranked outputs.

### Work Items
- Keep `hotspots` as the first deterministic ranking view.
- Add ownership and contribution aggregates needed for `ownership_entropy`.
- Add a recency-weighted churn measure for `recent_change_risk`.
- Add a coverage-derived metric only when coverage inputs exist.
- Make the outputs inspectable in SQL first unless a Python materialization is clearly simpler.

### Interfaces
- SQL views or query helpers should return:
  - file identity and repository identity
  - churn and complexity components
  - derived score values
  - supporting raw fields needed for explanation in the UI

### Tests
- Hotspot ranking uses churn and complexity consistently.
- Empty or sparse data does not produce division errors or null-handling bugs.
- Ties and ordering remain deterministic.
- Views continue to work when only Git-derived data exists.

### Exit Criteria
- Risk-related queries are available without application-side reconstruction.
- The score outputs are understandable from the underlying fields.

### Status
- Complete.

## Phase 4: Local Dashboard

### Goal
Expose the analytics in a simple local web UI that does not require external BI tooling.

### Work Items
- Add a lightweight local web app under `src/dashboards/`.
- Implement pages for:
  - risk leaderboard
  - hotspot map
  - file detail
  - ownership summary
- Prefer simple server-rendered tables and minimal charts over a heavy frontend stack.
- Wire the dashboard to the SQLite database directly through the analytics helpers.

### Tests
- Routes respond successfully in a local smoke test.
- Each primary page renders with representative seeded data.
- Empty-state rendering is handled without errors.

### Exit Criteria
- A user can open the local app and inspect the top-risk files and file detail views.

### Status
- Complete.

## Phase 5: Expand Ingestion Sources

### Goal
Add optional sources without destabilizing the core Git-and-SQLite workflow.

### Work Items
- Add schema and ingestion paths for:
  - CI/CD summaries
  - issue and incident data
  - dependency edges
  - runtime and coverage artifacts
- Keep each source modular so it can be enabled independently.
- Reuse `analysis_runs` for tracing each ingestion job type.
- Avoid forcing any source to exist before the dashboard or scoring logic can run.

### Tests
- Each new source has at least one focused ingestion or schema test.
- Optional sources do not break core Git ingestion when absent.

### Exit Criteria
- At least one non-Git source is modeled end-to-end without affecting the core ingest path.

### Status
- Complete.

## Phase 6: Packaging And Operations

### Goal
Make the project easy to run, inspect, and recover in a single-instance setup.

### Work Items
- Document local and single-instance deployment with `uv` and `task`.
- Add environment-variable-driven configuration for database path and host/port.
- Document backup and restore for the SQLite database.
- Keep ClickHouse and BI tooling as optional future adapters only.
- Make runtime defaults explicit so users do not need to read code to get started.

### Tests
- Configuration defaults resolve to the documented local setup.
- Documentation examples match the current commands and file paths.

### Exit Criteria
- A new user can install, ingest, and query the project using only the documented local workflow.

## Test Plan

- Keep the full `pytest` suite green.
- Add regression tests for:
  - schema migrations and migration checksum enforcement
  - idempotent Git ingestion
  - empty repository ingestion
  - deleted and renamed file handling
  - hotspot and analytics view correctness
  - dashboard route smoke tests
- Preserve coverage on core analytics and ingestion modules.

## Assumptions

- SQLite remains the default and primary storage engine.
- Git ingestion stays local-first and uses direct Git commands unless a later phase explicitly changes that.
- Dashboard work will prioritize a minimal local app over external BI integration.
- Future CI, issue, and runtime integrations remain optional and should not block the core pipeline.

## Suggested Execution Order

1. Packaging and operations
