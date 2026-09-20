"""Read the committed index. The API, `dab stats` and the tests go through here.

The index is loaded once per process and joined in memory: 54 queries, 12
datasets and roughly 14.5k answer rows are small.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from dab_bench.config import (
    ANSWERS_DIR,
    DATASETS_PATH,
    LEADERBOARD_PATH,
    MANIFEST_PATH,
    QUERIES_PATH,
    SOURCE_PATH,
    TRIALS_PATH,
    VALIDATORS_PATH,
)


@dataclass
class Index:
    source: dict[str, Any]
    datasets: list[dict[str, Any]]
    queries: list[dict[str, Any]]
    validators: dict[str, Any]
    manifest: list[dict[str, Any]]
    leaderboard: dict[str, Any]
    trials: dict[str, Any] | None
    answers: dict[str, dict[str, list[dict[str, Any]]]] = field(default_factory=dict)

    @property
    def dataset_by_key(self) -> dict[str, dict[str, Any]]:
        return {d["key"]: d for d in self.datasets}

    @property
    def query_by_id(self) -> dict[str, dict[str, Any]]:
        return {q["id"]: q for q in self.queries}

    def query_trials(self, qid: str) -> dict[str, Any] | None:
        if not self.trials:
            return None
        pq: dict[str, Any] = self.trials.get("per_query", {})
        return pq.get(qid)


def _load(path: Path) -> Any:
    return json.loads(path.read_text())


def _load_answers() -> dict[str, dict[str, list[dict[str, Any]]]]:
    """answers[query id][file name] -> rows, in file order (row index is the id trials.json uses)."""
    out: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(dict)
    if not ANSWERS_DIR.exists():
        return out
    for path in sorted(ANSWERS_DIR.glob("*.json")):
        name = path.stem
        for i, row in enumerate(_load(path)):
            out[row["id"]].setdefault(name, []).append({"i": i, **row})
    return out


def load(fresh: bool = False) -> Index:
    if fresh:
        _cached.cache_clear()
    return _cached()


@lru_cache(maxsize=1)
def _cached() -> Index:
    if not SOURCE_PATH.exists():
        raise FileNotFoundError(
            f"no index at {SOURCE_PATH.parent}; run `make upstream && make ingest`"
        )
    return Index(
        source=_load(SOURCE_PATH),
        datasets=_load(DATASETS_PATH),
        queries=_load(QUERIES_PATH),
        validators=_load(VALIDATORS_PATH),
        manifest=_load(MANIFEST_PATH),
        leaderboard=_load(LEADERBOARD_PATH),
        trials=_load(TRIALS_PATH) if TRIALS_PATH.exists() else None,
        answers=_load_answers(),
    )


def stats(ix: Index | None = None) -> dict[str, Any]:
    """The numbers the README quotes, computed from the index and nothing else."""
    ix = ix or load()
    src = ix.source
    styles = {s["style"]: s["n"] for s in ix.validators["styles"]}
    engines: dict[str, int] = defaultdict(int)
    for d in ix.datasets:
        for e in d["engines"]:
            engines[e] += 1
    out: dict[str, Any] = {
        "commit": src["commit"],
        "datasets_total_upstream": src["datasets_total"],
        "queries_total_upstream": src["queries_total"],
        "datasets": src["in_scope"]["datasets"],
        "queries": src["in_scope"]["queries"],
        "deferred_datasets": src["deferred"]["datasets"],
        "deferred_queries": src["deferred"]["queries"],
        "with_gold": sum(1 for q in ix.queries if q["gold_text"]),
        "with_validator": sum(1 for q in ix.queries if q["validator"]["source"]),
        "validator_styles": styles,
        "engines": dict(sorted(engines.items())),
        "bytes_in_scope": sum(m["bytes"] for m in ix.manifest if m["in_scope"]),
        "bytes_total": sum(m["bytes"] for m in ix.manifest),
        "answer_files": len(ix.leaderboard.get("answer_files", [])),
        "answer_rows": src["answer_rows"],
        "answer_rows_unmatched": src["answer_rows_unmatched"],
        "leaderboard_entries": len(ix.leaderboard.get("overallLeaderboard", [])),
        "rescored": ix.trials is not None,
    }
    if ix.trials:
        out["trials_judged"] = ix.trials["summary"]["rows"]
        out["never_passed"] = ix.trials["summary"]["never_passed"]
        out["under_10pct"] = ix.trials["summary"]["under_10pct"]
    return out
