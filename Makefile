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

.PHONY: help setup upstream ingest rescore stats dev build test lint fmt
