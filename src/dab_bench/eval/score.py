"""Result rows and the run summary: one row per (query, trial), pass rates with their denominators.

`pass_rate_macro` is the leaderboard's number (mean over datasets of the mean
per-query pass rate); `pass_rate_micro` is rows passed over rows scored. A query
with no scored trial is "not scored", never 0 (project rule).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TrialResult:
    query_id: str  # `crmarenapro/1`
    dataset: str
    trial: int  # 1-based
    question: str
    answer: str
    passed: bool | None  # None: not scored (dry run, validator missing)
    reason: str = ""
    n_turns: int = 0
    duration_ms: int = 0
    cost_usd: float | None = None
    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
    error: str | None = None
    terminal_reason: str | None = None
    timed_out: bool = False
    rate_limited: bool = False  # the subscription window closed: not scored, re-run with --resume
    trace_file: str | None = None
    mlflow_trace_id: str | None = None
    session_id: str | None = None
    # the SQL-answer contract (s06): what submit_answer recorded; None for a version without it
    agent_sql: str | None = None
    agent_result: str | None = None  # the harness's rendered re-run of agent_sql
    mode: str | None = None  # pass_through | derived
    step: str | None = None  # derived: the one-line step after the SQL
    result_rows: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DatasetRate:
    passed: int
    n: int
    rate: float | None
    queries: int


@dataclass
class Summary:
    n: int
    scored: int
    passed: int
    pass_rate_micro: float | None
    pass_rate_macro: float | None
    per_dataset: dict[str, dict[str, Any]]
    per_query: dict[str, dict[str, Any]]
    errors: int
    timeouts: int
    rate_limited: int
    cost_usd: float
    duration_ms: int
    turns_total: int
    input_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    output_tokens: int
    failed_queries: list[str] = field(default_factory=list)


def summarise(results: list[TrialResult]) -> Summary:
    scored = [r for r in results if r.passed is not None]
    by_query: dict[str, list[TrialResult]] = {}
    for r in scored:
        by_query.setdefault(r.query_id, []).append(r)
    per_query: dict[str, dict[str, Any]] = {
        q: {
            "dataset": rs[0].dataset,
            "passed": sum(1 for r in rs if r.passed),
            "n": len(rs),
            "rate": sum(1 for r in rs if r.passed) / len(rs),
        }
        for q, rs in by_query.items()
    }
    by_ds: dict[str, list[str]] = {}
    for q, e in per_query.items():
        by_ds.setdefault(str(e["dataset"]), []).append(q)
    per_dataset: dict[str, dict[str, Any]] = {}
    for ds, qs in by_ds.items():
        p = sum(int(per_query[q]["passed"]) for q in qs)
        n = sum(int(per_query[q]["n"]) for q in qs)
        macro_q = sum(float(per_query[q]["rate"]) for q in qs) / len(qs)
        per_dataset[ds] = {"passed": p, "n": n, "rate": macro_q, "queries": len(qs)}
    macro = (
        sum(float(v["rate"]) for v in per_dataset.values()) / len(per_dataset)
        if per_dataset
        else None
    )
    passed = sum(1 for r in scored if r.passed)
    return Summary(
        n=len(results),
        scored=len(scored),
        passed=passed,
        pass_rate_micro=passed / len(scored) if scored else None,
        pass_rate_macro=macro,
        per_dataset=per_dataset,
        per_query=per_query,
        errors=sum(1 for r in results if r.error and not r.rate_limited),
        timeouts=sum(1 for r in results if r.timed_out),
        rate_limited=sum(1 for r in results if r.rate_limited),
        cost_usd=sum(r.cost_usd or 0.0 for r in results),
        duration_ms=sum(r.duration_ms for r in results),
        turns_total=sum(r.n_turns for r in results),
        input_tokens=sum(r.input_tokens for r in results),
        cache_read_tokens=sum(r.cache_read_tokens for r in results),
        cache_creation_tokens=sum(r.cache_creation_tokens for r in results),
        output_tokens=sum(r.output_tokens for r in results),
        failed_queries=sorted(q for q, e in per_query.items() if e["passed"] == 0),
    )


def write_results(path: Path, results: list[TrialResult]) -> None:
    path.write_text("".join(json.dumps(r.as_dict(), ensure_ascii=False) + "\n" for r in results))


def read_results(path: Path) -> list[TrialResult]:
    out: list[TrialResult] = []
    for line in path.read_text().splitlines():
        if line.strip():
            out.append(TrialResult(**json.loads(line)))
    return out


# ── the production profile: what a run costs per trial, with its tail ─────────

PROFILE_METRICS: tuple[tuple[str, str], ...] = (
    ("turns", "turns per trial"),
    ("tool_calls", "tool calls per trial"),
    ("wall_s", "wall seconds per trial"),
    ("fresh_in", "fresh input tokens (uncached + cache writes)"),
    ("cache_read", "cache-read tokens"),
    ("output", "output tokens"),
    ("total", "total tokens (all input + output)"),
    ("cost_usd", "cost per trial (Agent SDK cost_usd)"),
)


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank on the sorted values (the same rule `dab runs profile` prints)."""
    if not values:
        return 0.0
    v = sorted(values)
    return v[min(len(v) - 1, round(p * (len(v) - 1)))]


def _series(r: TrialResult) -> dict[str, float]:
    fresh = float(r.input_tokens + r.cache_creation_tokens)
    return {
        "turns": float(r.n_turns),
        "tool_calls": float(r.tool_calls),
        "wall_s": r.duration_ms / 1000.0,
        "fresh_in": fresh,
        "cache_read": float(r.cache_read_tokens),
        "output": float(r.output_tokens),
        "total": fresh + r.cache_read_tokens + r.output_tokens,
        "cost_usd": r.cost_usd or 0.0,
    }


def profile(results: list[TrialResult]) -> dict[str, Any]:
    """Per-trial distributions (mean, p50, p95, max, sum) over every trial that ran, plus the
    ratios a reader wants at a glance. Rate-limited rows never ran, so they are excluded."""
    ran = [r for r in results if not r.rate_limited]
    cols: dict[str, list[float]] = {k: [] for k, _ in PROFILE_METRICS}
    for r in ran:
        for k, v in _series(r).items():
            cols[k].append(v)
    metrics = {
        k: {
            "mean": sum(v) / len(v) if v else 0.0,
            "p50": percentile(v, 0.5),
            "p95": percentile(v, 0.95),
            "max": max(v) if v else 0.0,
            "sum": sum(v),
        }
        for k, v in cols.items()
    }
    passed = sum(1 for r in ran if r.passed)
    scored = sum(1 for r in ran if r.passed is not None)
    cost = metrics["cost_usd"]["sum"]
    all_in = metrics["fresh_in"]["sum"] + metrics["cache_read"]["sum"]
    return {
        "n": len(ran),
        "metrics": metrics,
        "cache_hit_rate": metrics["cache_read"]["sum"] / all_in if all_in else None,
        "cost_per_pass": cost / passed if passed else None,
        "cost_per_trial": cost / len(ran) if ran else None,
        "tokens_per_pass": metrics["total"]["sum"] / passed if passed else None,
        "timeout_rate": sum(1 for r in ran if r.timed_out) / len(ran) if ran else None,
        "error_rate": sum(1 for r in ran if r.error) / len(ran) if ran else None,
        "fail_rate": (scored - passed) / scored if scored else None,
        # a failed trial that also hit max turns / timeout: the agent ran out, it did not answer wrong
        "exhausted": sum(
            1
            for r in ran
            if r.passed is False and (r.timed_out or r.terminal_reason == "max_turns")
        ),
    }
