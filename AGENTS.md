# Repository Guidelines

## Project Structure & Module Organization
- Implement features under `src/` with subpackages for `ingestion/`, `analytics/`, `modeling/`, and `dashboards/`. Mirror each Python module in `tests/` using the same subpackage name (e.g., `src/ingestion/git_loader.py` → `tests/ingestion/test_git_loader.py`).
- Store reusable SQL or ClickHouse DDL in `schema/`; keep exploratory notebooks in `notebooks/`. Generated data extracts live under `data/{raw,processed}/` and stay out of version control unless <10 KB fixtures.
- Use `configs/` for pipeline settings (YAML or TOML). Reference them via environment variables instead of hard-coding secrets.

## Build, Test, and Development Commands
- `task deps` — install or refresh the pinned runtime stack via `uv sync`. Regenerate lockfiles with `uv pip compile requirements.in --output-file requirements.txt` before running.
- `task format` — run `uv run ruff --fix` followed by `uv run black` to normalize style; required before every PR.
- `task test` — execute the full pytest suite with coverage using `uv run pytest`. Use `pytest -k <pattern>` only for focused debugging.
- `task data-check` — lint ETL assets (schema drift, missing columns) via validators in `src/analytics/validators/` through `uv run`.

## Coding Style & Naming Conventions
- Follow Python 3.11 standards: `black`-formatted (88 chars), `ruff` for linting, and type hints everywhere. Prefer dataclasses for structured records and `Path` over string paths.
- Modules: snake_case filenames; classes: PascalCase; functions and variables: snake_case; constants: UPPER_SNAKE_CASE. Keep CLI entry points in `src/cli/` named `cmd_<verb>.py`.
- For SQL, store queries as `.sql` templates with uppercase keywords and parameter placeholders like `{{ run_date }}` consistent with Jinja.

## Testing Guidelines
- Use `pytest` with fixtures in `tests/conftest.py`. Name tests after the behavior under inspection, e.g., `test_hotspot_score_handles_empty_metrics`.
- Target ≥85 % branch coverage on core analytics modules; add regression tests when fixing defects surfaced by risk models.
- Mock external systems (ClickHouse, Git APIs) with `pytest-mock` or `responses`. Integration tests that touch real services belong in `tests/integration/` and should be skipped by default using `@pytest.mark.integration`.

## Commit & Pull Request Guidelines
- Craft commits in present tense under 72 characters (e.g., `Add hotspot scoring pipeline`). Group related schema and code changes together; avoid drive-by refactors inside analytic PRs.
- Each PR must link to the tracking issue, summarize data sources touched, and include before/after metrics or screenshots for dashboards. Add a checklist covering tests, schema migrations, and validation runs.
- Request review from the analytics maintainer group and wait for CI success (`task test` + `task data-check`) before merging.
