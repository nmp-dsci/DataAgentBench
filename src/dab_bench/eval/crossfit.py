"""`dab crossfit RUN --prefix v7_sql --folds 3` (plan s11): an out-of-sample score for a round
that reads every error.

A round that reads all 54 questions leaves no held-out question to test it on. Cross-fitting
keeps that test without hiding anything from the version itself: the 54 are split into k folds,
stratified by dataset and seeded; for each fold the same round (same optimiser, same guards)
runs with that fold's questions excluded (`optimise(..., exclude=fold)`), and the fold's
prompt answers only that fold. Every question is then scored once, by a prompt that never
read it. The fold versions (`<prefix>_f1` …) carry `crossfit_of` in `agent.yaml`: they are
measurement prompts, outside every list and never promoted.

It measures the procedure (learn from errors), not the exact text of `<prefix>`; the gap
between `<prefix>`'s own score on the 54 (in-sample) and this one is how much of the round's
gain comes from fitting what it read. The record is `runs/<RUN>/crossfit/<prefix>.json`.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from dab_bench.config import RUNS_DIR

SEED = 20260925


def folds(qids: list[str], k: int = 3, seed: int = SEED) -> list[list[str]]:
    """`qids` in k folds, every dataset spread over them as evenly as it can be and the folds'
    sizes within one of each other; the same seed gives the same folds."""
    by_ds: dict[str, list[str]] = defaultdict(list)
    for q in sorted(qids):
        by_ds[q.split("/")[0]].append(q)
    out: list[list[str]] = [[] for _ in range(k)]
    turn = 0  # where the next dataset starts dealing, so small datasets do not pile on fold 1
    for ds in sorted(by_ds):
        qs = by_ds[ds]
        random.Random(f"{seed}:{ds}").shuffle(qs)
        for i, q in enumerate(qs):
            out[(turn + i) % k].append(q)
        turn = (turn + len(qs)) % k
    return [sorted(f) for f in out]


def pass_at_1(answers: dict[str, bool | None]) -> float | None:
    """The leaderboard's Pass@1 for one trial per question: the mean over datasets of each
    dataset's pass rate (unscored questions left out)."""
    by_ds: dict[str, list[bool]] = defaultdict(list)
    for q, a in answers.items():
        if a is not None:
            by_ds[q.split("/")[0]].append(bool(a))
    rates = [sum(v) / len(v) for v in by_ds.values() if v]
    return sum(rates) / len(rates) if rates else None


def _rows(run_id: str) -> dict[str, dict[str, Any]]:
    card = json.loads((RUNS_DIR / run_id / "scorecard.json").read_text())
    return {q["query_id"]: q for q in card["questions"] if q["trial"] == 1}


def stitch(fold_ids: list[list[str]], fold_runs: list[str]) -> dict[str, Any]:
    """Each fold's run scores only its own questions; together they score every question
    once, out of sample."""
    per: dict[str, dict[str, Any]] = {}
    for i, (ids, run_id) in enumerate(zip(fold_ids, fold_runs, strict=True), start=1):
        rows = _rows(run_id)
        for q in ids:
            r = rows.get(q, {})
            per[q] = {"fold": i, "answer": r.get("answer"), "sql": r.get("sql")}
    answers = {q: v["answer"] for q, v in per.items()}
    sql = [v["sql"] for v in per.values() if v["sql"] is not None]
    return {
        "questions": dict(sorted(per.items())),
        "answer": {
            "passed": sum(1 for a in answers.values() if a),
            "n": sum(1 for a in answers.values() if a is not None),
        },
        "sql": {"passed": sum(1 for x in sql if x), "n": len(sql)},
        "pass_at_1": pass_at_1(answers),
    }


async def crossfit(
    run_id: str,
    prefix: str,
    k: int = 3,
    model: str | None = None,
    strict: bool = True,
    workers: int = 4,
    seed: int = SEED,
) -> dict[str, Any]:
    """k fold rounds on RUN's errors, each fold answered by its own prompt, then stitched."""
    from dab_bench.agent.optimise import optimise
    from dab_bench.eval.runner import run_eval
    from dab_bench.eval.scorecard import load_scorecard, score_run

    card = load_scorecard(run_id) or score_run(run_id)
    everyone = sorted({q["query_id"] for q in card["questions"] if q["trial"] == 1})
    fs = folds(everyone, k, seed)
    started = datetime.now(UTC).isoformat()
    rounds: list[dict[str, Any]] = []
    fold_runs: list[str] = []
    for i, fold in enumerate(fs, start=1):
        name = f"{prefix}_f{i}"
        rec = await optimise(
            run_id,
            name,
            workers=workers,
            model=model,
            train_all=True,
            exclude=set(fold),
            strict=strict,
            crossfit={"of": prefix, "fold": i, "k": k, "seed": seed, "holds_out": fold},
        )
        rounds.append({"version": name, "cost_usd": rec.get("cost_usd")})
        meta, _ = await run_eval(
            agent=name,
            split="all",
            trials=1,
            workers=workers,
            query_ids=fold,
            note=f"crossfit fold {i}/{k} of {prefix} (s11): answers only the questions it never read",
        )
        score_run(meta.run_id)
        fold_runs.append(meta.run_id)
        rounds[-1] |= {
            "run_id": meta.run_id,
            "eval_cost_usd": (meta.summary or {}).get("cost_usd"),
        }
    out = {
        "prefix": prefix,
        "source_run": run_id,
        "k": k,
        "seed": seed,
        "strict": strict,
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "folds": fs,
        "rounds": rounds,
        "out_of_sample": stitch(fs, fold_runs),
        "cost_usd": sum(
            (r.get("cost_usd") or 0.0) + (r.get("eval_cost_usd") or 0.0) for r in rounds
        ),
    }
    d = RUNS_DIR / run_id / "crossfit"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{prefix}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    return out


def export_submission(run_id: str) -> tuple[str, int]:
    """The run's answers in the leaderboard's submission format (`dataset`, `query`, `run`,
    `answer`; the dataset spelled as its upstream folder, runs from 0), written to
    `runs/<RUN>/submission.json`. Local only: submitting is a pull request upstream."""
    from dab_bench.data.index import load

    ix = load()
    folder = {d["key"]: str(d["folder"]).removeprefix("query_") for d in ix.datasets}
    out = []
    for line in (RUNS_DIR / run_id / "results.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        ds, n = r["query_id"].rsplit("/", 1)
        out.append(
            {
                "dataset": folder.get(ds, ds),
                "query": n,
                "run": str(int(r["trial"]) - 1),
                "answer": str(r.get("answer") or ""),
            }
        )
    out.sort(key=lambda x: (x["dataset"], int(x["query"]), int(x["run"])))
    path = RUNS_DIR / run_id / "submission.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    return str(path), len(out)
