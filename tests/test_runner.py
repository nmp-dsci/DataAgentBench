"""The harness without a model: the split, the summary arithmetic, the run folder round trip, the runs API.

`summarise()` must match the index's arithmetic: micro = rows passed / rows
scored, macro = mean over datasets of the mean per-query rate; a rate-limited
row is not scored and never counts as a fail.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dab_bench.eval import runner
from dab_bench.eval.score import TrialResult, read_results, summarise, write_results
from dab_bench.eval.splits import load_split
from dab_bench.serving import app as serving


def _row(q: str, trial: int, passed: bool | None, **kw: object) -> TrialResult:
    ds = q.split("/")[0]
    return TrialResult(q, ds, trial, "question?", "42", passed, **kw)  # type: ignore[arg-type]


def test_smoke_split_is_one_query_per_dataset() -> None:
    qs = load_split("smoke")
    assert len(qs) == 12
    assert len({q.dataset for q in qs}) == 12
    assert len(load_split("all")) == 54


def test_summary_macro_is_mean_over_datasets_and_rate_limited_is_not_scored() -> None:
    rows = [
        _row("a/1", 1, True),
        _row("a/1", 2, False),
        _row("a/2", 1, True),
        _row("b/1", 1, False),
        _row("b/1", 2, None, rate_limited=True, error="rate_limited: window closed"),
    ]
    s = summarise(rows)
    assert (s.n, s.scored, s.passed) == (5, 4, 2)
    assert s.pass_rate_micro == 0.5
    # a: queries at 0.5 and 1.0 → 0.75; b: 0.0 → macro 0.375
    assert s.pass_rate_macro == pytest.approx(0.375)
    assert s.per_dataset["a"] == {"passed": 2, "n": 3, "rate": 0.75, "queries": 2}
    assert s.rate_limited == 1 and s.errors == 0
    assert s.failed_queries == ["b/1"]


def test_profile_percentiles_and_ratios_exclude_rate_limited_rows() -> None:
    from dab_bench.eval.score import profile

    rows = [
        _row("a/1", 1, True, n_turns=10, cost_usd=0.10, cache_read_tokens=900, input_tokens=100),
        _row(
            "a/1",
            2,
            False,
            n_turns=30,
            cost_usd=0.30,
            timed_out=True,
            cache_read_tokens=100,
            input_tokens=100,
        ),
        _row("a/1", 3, None, rate_limited=True, n_turns=0),
    ]
    p = profile(rows)
    assert p["n"] == 2
    assert p["metrics"]["turns"] == {
        "mean": 20.0,
        "p50": 10.0,
        "p95": 30.0,
        "max": 30.0,
        "sum": 40.0,
    }
    assert p["cost_per_pass"] == pytest.approx(0.40) and p["cost_per_trial"] == pytest.approx(0.20)
    assert p["cache_hit_rate"] == pytest.approx(1000 / 1200)
    assert p["timeout_rate"] == 0.5 and p["exhausted"] == 1 and p["fail_rate"] == 0.5


def test_results_round_trip(tmp_path: Path) -> None:
    rows = [_row("a/1", 1, True, cost_usd=0.1, n_turns=3), _row("a/1", 2, None, rate_limited=True)]
    write_results(tmp_path / "r.jsonl", rows)
    back = read_results(tmp_path / "r.jsonl")
    assert back == rows


def test_runs_api_lists_folders_and_serves_traces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "20260101T000000Z_v0_smoke_haiku"
    (run_dir / "traces").mkdir(parents=True)
    rows = [_row("bookreview/2", 1, True, trace_file="traces/bookreview_2_t1.json")]
    write_results(run_dir / "results.jsonl", rows)
    meta = runner.RunMeta(
        run_id=run_dir.name,
        agent="v0",
        fingerprint="abc",
        context_sha="def",
        model="claude-haiku-4-5",
        effort="medium",
        split="smoke",
        n_queries=1,
        trials=1,
        workers=1,
        hints=False,
        dry_run=False,
        started_at="2026-01-01T00:00:00+00:00",
        max_turns=60,
    )
    from dataclasses import asdict

    meta.summary = asdict(summarise(rows))
    (run_dir / "run.json").write_text(json.dumps(asdict(meta)))
    (run_dir / "traces" / "bookreview_2_t1.json").write_text(
        json.dumps({"answer": "42", "trace": []})
    )
    monkeypatch.setattr(runner, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(serving, "RUNS_DIR", tmp_path)
    client = TestClient(serving.create_app())
    board = client.get("/api/runs").json()
    listed = board["runs"]
    assert [r["run_id"] for r in listed] == [run_dir.name]
    assert (
        listed[0]["passed"] == 1
        and listed[0]["scored"] == 1
        and listed[0]["pass_rate_macro"] == 1.0
    )
    # a smoke run is never the champion, whatever its score
    assert listed[0]["role"] == "smoke" and board["champion_run_id"] is None
    assert listed[0]["profile"]["n"] == 1 and listed[0]["profile"]["metrics"]["turns"]["p95"] == 0
    detail = client.get(f"/api/runs/{run_dir.name}").json()
    assert detail["passed"] == 1 and detail["results"][0]["query_id"] == "bookreview/2"
    assert detail["versus"] is None
    trace = client.get(f"/api/runs/{run_dir.name}/traces/bookreview_2_t1").json()
    assert trace["answer"] == "42" and trace["passed"] is True and trace["spans"] == []
    assert client.get("/api/runs/nope").status_code == 404
