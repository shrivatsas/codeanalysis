# Codeanalysis

Local-first code analytics on SQLite.

## Quick Start

```bash
task deps
task test
```

## Typical Workflow

1. Ingest Git history.
   ```bash
   uv run python -m src.cli.cmd_ingest_git \
     --repo ~/Documents/houseworks/emr/emr-api \
     --db data/codeanalysis-emr-api.db
   ```

2. Collect static metrics.
   ```bash
   uv run python -m src.cli.cmd_collect_metrics \
     --repo ~/Documents/houseworks/emr/emr-api \
     --db data/codeanalysis-emr-api.db
   ```

3. Import coverage data when you have a JSON report.
   ```bash
   uv run python -m src.cli.cmd_ingest_coverage \
     --repo ~/Documents/houseworks/emr/emr-api \
     --coverage-file /path/to/coverage.json \
     --db data/codeanalysis-emr-api.db
   ```

4. Download a CI/CD summary from GitHub Actions when you want a fresh report.
   ```bash
   uv run python -m src.cli.cmd_download_ci \
     --repo owner/name \
     --output ci.json
   ```
   This requires the GitHub CLI (`gh`) to be installed and authenticated
   (`gh auth status` / `gh auth login`). The repository slug must be in
   `owner/name` form.

5. Import CI/CD summaries when you have a JSON report.
   ```bash
   uv run python -m src.cli.cmd_ingest_ci \
     --repo ~/Documents/houseworks/emr/emr-api \
     --ci-file /path/to/ci.json \
     --db data/codeanalysis-emr-api.db
   ```

6. Start the dashboard.
   ```bash
   task dashboard
   ```

## Environment Variables

These defaults are shared across the CLIs and the dashboard server:

| Variable | Default | Purpose |
| --- | --- | --- |
| `CODEANALYSIS_DB_PATH` | `data/codeanalysis.db` | Default SQLite database path |
| `CODEANALYSIS_DASHBOARD_HOST` | `127.0.0.1` | Dashboard bind address |
| `CODEANALYSIS_DASHBOARD_PORT` | `8000` | Dashboard port |

If you set `CODEANALYSIS_DB_PATH`, the `--db` flag defaults to that path.
If you set the dashboard host or port variables, `task dashboard` and
`uv run python -m src.cli.cmd_serve_dashboard` use them automatically.

## Backup And Restore

SQLite is the system of record, so the simplest backup is a direct file copy
when the app is not writing to the database.

Backup:

```bash
mkdir -p backups
sqlite3 "${CODEANALYSIS_DB_PATH:-data/codeanalysis.db}" \
  ".backup 'backups/codeanalysis.db'"
```

Restore:

```bash
cp backups/codeanalysis.db "${CODEANALYSIS_DB_PATH:-data/codeanalysis.db}"
```

If you are running the dashboard or an ingest job, stop it before restoring so
the SQLite file and any WAL state stay consistent.
