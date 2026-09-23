# DataAgentBench explorer — every target is a thin wrapper over `uv run dab …`.
.DEFAULT_GOAL := help
WORKERS ?= 4
TIMEOUT ?= 30
PORT ?= 8091

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n", $$1, $$2}'

setup: ## install python deps (uv) and frontend deps (npm)
	uv sync
	cd frontend && npm ci

upstream: ## shallow-clone the benchmark into data/upstream (LFS skipped; no database bytes)
	uv run dab upstream

ingest: ## walk data/upstream → data/index/*.json + data/answers/*.json (committed)
	uv run dab ingest

rescore: ## judge every committed answer with its validate.py → data/index/trials.json (needs data/upstream)
	uv run dab rescore --workers $(WORKERS) --timeout $(TIMEOUT)

stats: ## the numbers the README quotes, from the index
	uv run dab stats

# ---- the agent build (plan s01) --------------------------------------------
platform-up: ## start nmp-central-ai's stack (MLflow :5000, Postgres :5432) — rule zero: never our own copy
	$(MAKE) -C ../nmp-central-ai up

db-roles: ## apply infra/roles.sql to database `dab` on the central Postgres (idempotent)
	uv run dab data init

db-smoke: ## zero-model proof the central database serves this project (run by nmp-central-ai's `make check`)
	uv run dab data smoke

db-reset: ## drop and recreate ONLY this project's schema inside database `dab`, then roles.sql (asks first)
	@read -p "Drop schema dataagentbench in database dab? [y/N] " a && [ "$$a" = "y" ] || { echo kept; exit 1; }
	uv run python -c "import psycopg; from dab_bench.config import settings; c=psycopg.connect(settings().pg_superuser_url, autocommit=True); c.execute('DROP SCHEMA IF EXISTS dataagentbench CASCADE'); print('dropped')"
	uv run dab data init

data: ## download the 12 datasets' database files (8.4 GB, sha256-verified) and load them into Postgres
	uv run dab data download
	uv run dab data load
	uv run dab data check

questions: ## copy data/index/queries.json into dataagentbench_meta for ad-hoc SQL (holds gold; not granted to dab_agent)
	uv run dab data load-questions

context: ## generate the context pack from Postgres (schema, profile, samples, joins) — no model
	uv run dab context build

curate: ## the curator agent writes summary.md + pitfalls.md per dataset (Sonnet 5, once, never sees a question)
	uv run dab context curate

sandbox: ## build the execute_python sandbox image (python:3.12-slim + pandas, duckdb, scipy)
	docker build -t dab-sandbox:py312 -f infra/sandbox.Dockerfile infra

AGENT ?= champion
SPLIT ?= smoke
TRIALS ?= 1
EVAL_WORKERS ?= 4
eval: ## run AGENT (default champion) on SPLIT (smoke|all) × TRIALS; needs platform-up, db-roles, sandbox
	uv run dab eval --agent $(AGENT) --split $(SPLIT) --trials $(TRIALS) --workers $(EVAL_WORKERS)

dev: ## run the API on :$(PORT) (frontend: cd frontend && npm run dev → :5173)
	uv run dab serve --port $(PORT) --reload

build: ## build the explorer into frontend/dist so `make dev` serves it on one port
	cd frontend && npm run build

test: ## pytest
	uv run pytest -q

lint: ## ruff + mypy (+ frontend typecheck and design lint when node_modules exist)
	uv run ruff format --check src tests && uv run ruff check src tests && uv run mypy
	@test -d frontend/node_modules && (cd frontend && npm run typecheck && npm run lint:design) || true

fmt: ## ruff format + fix
	uv run ruff format src tests && uv run ruff check --fix src tests

.PHONY: help setup upstream ingest rescore stats dev build test lint fmt platform-up db-roles db-smoke db-reset data questions context curate sandbox eval
