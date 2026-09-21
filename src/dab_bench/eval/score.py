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
