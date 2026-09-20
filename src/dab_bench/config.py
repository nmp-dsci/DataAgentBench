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
CONTEXT_DIR = DATA_DIR / "context"
FRONTEND_DIST = ROOT / "frontend" / "dist"

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
    """Runtime settings, read once from the environment."""

    upstream_commit: str | None = None
    code_sha: str = "unknown"

    @classmethod
    def from_env(cls) -> Settings:
        commit = os.environ.get("DAB_UPSTREAM_COMMIT", "").strip() or None
        return cls(upstream_commit=commit, code_sha=os.environ.get("DAB_CODE_SHA", "unknown"))


def settings() -> Settings:
    return Settings.from_env()
