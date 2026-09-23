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

from dab_bench.config import TRIALS_PATH
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


def _write_run(root: Path, run_id: str, rows: list[TrialResult], split: str = "smoke") -> None:
    from dataclasses import asdict

    d = root / run_id
    d.mkdir(parents=True)
    write_results(d / "results.jsonl", rows)
    meta = runner.RunMeta(
        run_id=run_id,
        agent="v0",
        fingerprint="abc",
        context_sha="def",
        model="claude-haiku-4-5",
        effort="medium",
        split=split,
        n_queries=len({r.query_id for r in rows}),
        trials=1,
        workers=1,
        hints=False,
        dry_run=False,
        started_at="2026-01-01T00:00:00+00:00",
        max_turns=60,
    )
    meta.summary = asdict(summarise(rows))
    (d / "run.json").write_text(json.dumps(asdict(meta)))


def test_compare_two_runs_on_their_common_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # focus scored three queries; the challenger two of them plus one rate-limited row
    _write_run(
        tmp_path,
        "a",
        [_row("bookreview/2", 1, True), _row("yelp/1", 1, False), _row("agnews/1", 1, False)],
    )
    _write_run(
        tmp_path,
        "b",
        [
            _row("bookreview/2", 1, False),
            _row("yelp/1", 1, True),
            _row("agnews/1", 1, None, rate_limited=True),
        ],
    )
    monkeypatch.setattr(runner, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(serving, "RUNS_DIR", tmp_path)
    client = TestClient(serving.create_app())

    r = client.get("/api/runs/compare", params={"focus": "a", "challenger": "b"}).json()
    # agnews/1 is rate-limited in b, so it is not scored there and not common
    assert r["common_queries"] == 2 and r["scored_queries"] == {"a": 3, "b": 2}
    assert r["sides"]["a"]["scored"] == 2 and r["sides"]["b"]["scored"] == 2
    assert r["fixed"] == ["yelp/1"] and r["broken"] == ["bookreview/2"]
    assert [g["key"] for g in r["groups"]] == ["bookreview", "yelp"]

    # each run on its own queries: the focus keeps agnews/1
    own = client.get(
        "/api/runs/compare", params={"focus": "a", "challenger": "b", "scope": "all"}
    ).json()
    assert own["sides"]["a"]["scored"] == 3 and "agnews" in [g["key"] for g in own["groups"]]

    style = client.get("/api/runs/compare", params={"focus": "a", "group": "style"}).json()
    assert style["challenger"] is None and style["scope"] == "all"
    assert sum(g["a"]["n"] for g in style["groups"]) == 3  # every scored trial lands in one style

    assert client.get("/api/runs/compare", params={"focus": "nope"}).status_code == 404
    assert client.get("/api/runs/compare", params={"focus": "a", "group": "x"}).status_code == 400


@pytest.mark.skipif(not TRIALS_PATH.exists(), reason="not rescored")
def test_compare_a_run_against_a_leaderboard_submission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_run(tmp_path, "a", [_row("bookreview/2", 1, True), _row("yelp/1", 1, False)])
    monkeypatch.setattr(runner, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(serving, "RUNS_DIR", tmp_path)
    client = TestClient(serving.create_app())
    trials = json.loads(TRIALS_PATH.read_text())

    subs = client.get("/api/runs").json()["submissions"]
    assert [s["name"] for s in subs[:2]] == ["permute_eq", "oceanbase_lab_scout"]
    assert subs[0]["rank"] == 1 and subs[0]["pooled"] is False

    # the submission alone: every query it answered, scored exactly as the rescore did
    alone = client.get("/api/runs/compare", params={"focus": "lb:oceanbase_lab_scout"}).json()
    side = alone["sides"]["lb:oceanbase_lab_scout"]
    pf = trials["per_file"]["oceanbase_lab_scout"]
    assert side["passed"] == pf["passed"] and side["scored"] == pf["rows"]
    assert side["pass_rate_macro"] == pytest.approx(pf["macro"])
    assert side["profile"] is None and side["cost_usd"] is None and side["run"] is None

    # against our run: only the two queries the run scored are common
    r = client.get("/api/runs/compare", params={"focus": "a", "challenger": "lb:permute_eq"}).json()
    assert r["common_queries"] == 2
    lb = r["sides"]["lb:permute_eq"]
    assert lb["scored"] == 10 and lb["submission"]["label"].startswith("Permute EQ")
    assert r["sides"]["a"]["profile"] is not None

    assert client.get("/api/runs/compare", params={"focus": "lb:nope"}).status_code == 404
