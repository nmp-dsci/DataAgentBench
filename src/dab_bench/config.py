"""Paths and settings. One place; nothing else reads `os.environ` for these."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
UPSTREAM_DIR = DATA_DIR / "upstream"
INDEX_DIR = DATA_DIR / "index"
ANSWERS_DIR = DATA_DIR / "answers"
CONTEXT_DIR = DATA_DIR / "context"  # the context pack: committed text, one folder per dataset
SPLITS_DIR = DATA_DIR / "splits"
AGENTS_DIR = ROOT / "agents"
RUNS_DIR = ROOT / "runs"
WORKSPACE_DIR = ROOT / "workspace"
INFRA_DIR = ROOT / "infra"
FRONTEND_DIST = ROOT / "frontend" / "dist"

# The one schema this project owns on the (for now project-local, later central)
# Postgres, and the naming rule for every table in it: `<dataset>_<table>`.
PG_SCHEMA = "dataagentbench"
# The question set's convenience copy. A separate schema on purpose: PG_SCHEMA grants
# SELECT to dab_agent by default, so gold answers must not live there (infra/roles.sql).
PG_META_SCHEMA = "dataagentbench_meta"
HF_DATA_REPO = "ruiyingm/DataAgentBench-data"
MLFLOW_EXPERIMENT = "dataagentbench/evals"

UPSTREAM_REPO = "https://github.com/ucbepic/DataAgentBench.git"
UPSTREAM_PAPER = "https://arxiv.org/abs/2603.20576"

# The index files `dab ingest` writes. Everything the API and the explorer read is one of these.
SOURCE_PATH = INDEX_DIR / "source.json"
DATASETS_PATH = INDEX_DIR / "datasets.json"
QUERIES_PATH = INDEX_DIR / "queries.json"
VALIDATORS_PATH = INDEX_DIR / "validators.json"
MANIFEST_PATH = INDEX_DIR / "manifest.json"
LEADERBOARD_PATH = INDEX_DIR / "leaderboard.json"
TRIALS_PATH = INDEX_DIR / "trials.json"
VERDICTS_PATH = INDEX_DIR / "verdicts.jsonl"
ATTRIBUTION_PATH = INDEX_DIR / "ATTRIBUTION.md"


class Settings(BaseModel):
    """Runtime settings, read once from the environment.

    Boots keyless: the explorer, the ingest and the scorer never reach a model or a
    database. `database_url` is the owner connection for `dab data load`;
    `agent_database_url` is what the agent's `query_db` connects as (read-only role).
    """

    upstream_commit: str | None = None
    code_sha: str = "unknown"
    # The central Postgres (nmp-central-ai, database `dab`, platform decision D13); the
    # superuser is the platform's (D16). `make -C ../nmp-central-ai db-urls` prints these.
    database_url: str = "postgresql://dab_owner:dab_owner@localhost:5432/dab"
    agent_database_url: str = "postgresql://dab_agent:dab_agent@localhost:5432/dab"
    pg_superuser_url: str = "postgresql://nmp:nmp@localhost:5432/dab"
    mlflow_tracking_uri: str = "http://localhost:5000"
    billing: str = "subscription"
    # The explorer's playground may run llm_extract (a model call on the subscription)
    # only when this is set; decision D8-A keeps it off (plan s02 §04).
    playground_llm: bool = False

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ.get
        commit = env("DAB_UPSTREAM_COMMIT", "").strip() or None
        return cls(
            upstream_commit=commit,
            code_sha=env("DAB_CODE_SHA", "unknown"),
            database_url=env("DATABASE_URL", cls.model_fields["database_url"].default),
            agent_database_url=env(
                "AGENT_DATABASE_URL", cls.model_fields["agent_database_url"].default
            ),
            pg_superuser_url=env("PG_SUPERUSER_URL", cls.model_fields["pg_superuser_url"].default),
            mlflow_tracking_uri=env("MLFLOW_TRACKING_URI", "http://localhost:5000"),
            billing=env("BILLING", "subscription").strip().lower(),
            playground_llm=env("DAB_PLAYGROUND_LLM", "").strip() == "1",
        )


def settings() -> Settings:
    return Settings.from_env()
