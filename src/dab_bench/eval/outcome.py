"""Each optimisation round's outcome (plan s13, B2): did the version it wrote win, and what it
gained and lost against the run it learned from.

A round (`agents/<version>/optimise.json`) read one run (`source_run`, its parent's) and wrote
a version. Its outcome is read from two records, never from a model:

- `agents/promotions.jsonl`: **won** when the version won a promotion it stood in, **lost**
  when it stood (with a complete run) and never won, **pending** when it has not stood yet;
- the two runs' scorecards: per question and per column (answer of the 54, SQL of the
  questions with a golden), what passed under the parent and fails under the version
  (**lost**) and the reverse (**gained**), with the step each lost statement now breaks at.

`dab promote` writes the outcome of every round version it weighed onto that round's MLflow
run (tag `outcome`, artifact `outcome.json`), and `dab mlflow-backfill` does the same for the
rounds already run. The next round reads it back through `dab history` (`eval/history.py`).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dab_bench.config import AGENTS_DIR, RUNS_DIR

COLUMNS = ("answer", "sql")


def rows(card: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """A scorecard's trial-1 rows by question id."""
    return {q["query_id"]: q for q in (card or {}).get("questions", []) if q.get("trial", 1) == 1}


def pass_at_1(r: dict[str, dict[str, Any]]) -> float | None:
    """The leaderboard's Pass@1 over one trial: the mean over datasets of each dataset's rate."""
    by_ds: dict[str, list[bool]] = {}
    for q, row in r.items():
        if row.get("answer") is not None:
            by_ds.setdefault(q.split("/")[0], []).append(bool(row["answer"]))
    rates = [sum(v) / len(v) for v in by_ds.values() if v]
    return sum(rates) / len(rates) if rates else None


def moves(
    before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Per column: passed before/after (of the questions scored on both sides), and the ids
    gained and lost; a lost statement carries the step it now breaks at."""
    out: dict[str, dict[str, Any]] = {}
    for col in COLUMNS:
        both = [
            q
            for q in sorted(before)
            if q in after and before[q].get(col) is not None and after[q].get(col) is not None
        ]
        gained = [q for q in both if before[q][col] is False and after[q][col] is True]
        lost = [q for q in both if before[q][col] is True and after[q][col] is False]
        out[col] = {
            "n": len(both),
            "before": sum(1 for q in both if before[q][col]),
            "after": sum(1 for q in both if after[q][col]),
            "gained": gained,
            "lost": lost,
            "lost_breaks_at": {q: after[q].get("breaks_at") for q in lost},
        }
    return out


def _stood(p: dict[str, Any], version: str) -> dict[str, Any] | None:
    """The version's line in promotion `p` when it stood: a complete run, and not a challenger
    the leak gate barred (D46)."""
    return next(
        (
            c
            for c in p.get("candidates") or []
            if c.get("version") == version
            and c.get("run_id")
            and not c.get("why_not")
            and (not c.get("gate") or p.get("incumbent") == version)
        ),
        None,
    )


def round_outcome(
    rec: dict[str, Any],
    promotions: list[dict[str, Any]],
    card: Callable[[str], dict[str, Any] | None],
    latest_run: str | None = None,
) -> dict[str, Any]:
    """The outcome of one round record. `card(run_id)` reads a scorecard; `latest_run` is the
    version's newest complete run, used when no promotion names one."""
    version = rec["version"]
    stood = [(p, c) for p in promotions if (c := _stood(p, version))]
    won = [(p, c) for p, c in stood if p.get("winner") == version]
    deciding = won[0] if won else stood[-1] if stood else None
    run_id = deciding[1]["run_id"] if deciding else latest_run
    before = rows(card(rec["source_run"]))
    after = rows(card(run_id)) if run_id else {}
    vs = moves(before, after) if after else {}
    if vs:
        vs["pass_at_1"] = {"before": pass_at_1(before), "after": pass_at_1(after)}
    return {
        "version": version,
        "parent": rec.get("challenger_of"),
        "source_run": rec["source_run"],
        "run_id": run_id,
        "outcome": "won" if won else "lost" if stood else "pending",
        "promotion": (
            {k: deciding[0].get(k) for k in ("at", "incumbent", "winner", "reason")}
            if deciding
            else None
        ),
        "vs_parent": vs,
    }


# ── read from the folders ───────────────────────────────────────────────────


def load_promotions(agents_dir: Path = AGENTS_DIR) -> list[dict[str, Any]]:
    p = agents_dir / "promotions.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def folder_card(runs_dir: Path = RUNS_DIR) -> Callable[[str], dict[str, Any] | None]:
    def _card(run_id: str) -> dict[str, Any] | None:
        p = runs_dir / run_id / "scorecard.json"
        return json.loads(p.read_text()) if p.exists() else None

    return _card


def round_records(agents_dir: Path = AGENTS_DIR) -> list[dict[str, Any]]:
    """Every round record, oldest first; a cross-fit fold is a measurement, not a round."""
    recs = []
    for p in sorted(agents_dir.glob("*/optimise.json")):
        rec = json.loads(p.read_text())
        if rec.get("crossfit"):
            continue
        rec.setdefault("version", p.parent.name)
        recs.append(rec)
    return sorted(recs, key=lambda r: str(r.get("started_at") or ""))


def latest_full_run(version: str, runs_dir: Path = RUNS_DIR) -> str | None:
    """The version's newest complete full-split run (the rule `dab promote` uses)."""
    best: tuple[str, str] | None = None
    for d in runs_dir.iterdir() if runs_dir.exists() else []:
        p = d / "run.json"
        if not p.exists():
            continue
        m = json.loads(p.read_text())
        s = m.get("summary") or {}
        if (
            m.get("agent") != version
            or m.get("split") != "all"
            or m.get("dry_run")
            or not s
            or s.get("scored") != s.get("n")
            or s.get("rate_limited")
        ):
            continue
        if best is None or m["started_at"] > best[0]:
            best = (m["started_at"], m["run_id"])
    return best[1] if best else None


def all_outcomes(
    agents_dir: Path = AGENTS_DIR, runs_dir: Path = RUNS_DIR
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(round record, outcome) for every round, from the folders."""
    proms = load_promotions(agents_dir)
    card = folder_card(runs_dir)
    return [
        (rec, round_outcome(rec, proms, card, latest_full_run(rec["version"], runs_dir)))
        for rec in round_records(agents_dir)
    ]


# ── written to MLflow ───────────────────────────────────────────────────────


def log_outcome(rec: dict[str, Any], out: dict[str, Any]) -> bool:
    """Tag the round's MLflow run with its outcome and log `outcome.json`; False when the round
    has no MLflow run."""
    run_id = rec.get("mlflow_run_id")
    if not run_id:
        return False
    from mlflow import MlflowClient

    from dab_bench.tracking.mlflow_log import _client_setup

    _client_setup()
    client = MlflowClient()
    client.set_tag(run_id, "outcome", out["outcome"])
    client.set_tag(run_id, "outcome_vs", (out.get("promotion") or {}).get("incumbent") or "")
    client.set_tag(run_id, "outcome_run", out.get("run_id") or "")
    for col, m in (out.get("vs_parent") or {}).items():
        if col in COLUMNS:
            client.log_metric(run_id, f"outcome_{col}_gained", float(len(m["gained"])))
            client.log_metric(run_id, f"outcome_{col}_lost", float(len(m["lost"])))
    client.log_dict(run_id, out, "outcome.json")
    return True


def relog_record(rec: dict[str, Any], agents_dir: Path = AGENTS_DIR) -> bool:
    """Replace the round's `optimise.json` on its MLflow run with the folder's (a system pass
    re-run after the round was logged changes the record, not the MLflow copy)."""
    run_id = rec.get("mlflow_run_id")
    path = agents_dir / rec["version"] / "optimise.json"
    if not run_id or not path.exists():
        return False
    from mlflow import MlflowClient

    from dab_bench.tracking.mlflow_log import _client_setup

    _client_setup()
    MlflowClient().log_artifact(run_id, str(path))
    return True


def log_all(versions: list[str] | None = None) -> dict[str, str]:
    """Write every round's outcome (or only `versions`') to MLflow: {version: outcome}."""
    done = {}
    for rec, out in all_outcomes():
        if versions is not None and rec["version"] not in versions:
            continue
        if log_outcome(rec, out):
            done[rec["version"]] = out["outcome"]
    return done
