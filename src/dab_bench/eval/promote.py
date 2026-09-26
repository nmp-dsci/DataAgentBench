"""`dab promote`: the champion is the version that answers best on the leaderboard's number,
among those whose text passed the leak guards (D46).

Each candidate version is represented by its newest complete run of the full split: not a
dry run, every trial scored (a rate-limited trial must be resumed first). The rule (s14,
D46, replacing D36's SQL-first rule of s08, which replaced D30's answers-only rule): a
challenger takes the title only through the **leak gate**: the round that made it ran guards
G1–G4 (`dab optimise --strict`) over every text it wrote, so what it adds to the champion it
started from passed them (a model switch is judged by the version it copied; a base version
was written with no gold in sight), and G2 finds no gold value anywhere in its prompt. The incumbent stands without the gate. Of those standing, the highest **Pass@1** (the
mean over datasets of each one's pass rate, one trial) wins; the most **answers passed** of
the 54 break a tie, then the most **SQL passed** of the questions with a golden; a tie on all
three keeps the incumbent; a tie between two challengers goes to whichever's newest complete
full-split run started first (the older run). The verdict appends to
`agents/promotions.jsonl`, with the rule's name, every candidate's top lines, its gate, its
scorecard and its held-out result, and `agents/champion` moves when the winner changes. The
winner's prompt gets the `champion` alias in the MLflow prompt registry, and (s13, B2) every
round version weighed gets its outcome on its round's MLflow run (`eval/outcome.py`), which
the next round's history reads.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from dab_bench.agent.versions import (
    CHAMPION_FILE,
    champion_name,
    list_versions,
    load_notes,
    load_version,
)
from dab_bench.config import AGENTS_DIR

PROMOTIONS = AGENTS_DIR / "promotions.jsonl"


@dataclass
class Candidate:
    version: str
    run_id: str | None
    passed: int | None
    scored: int | None
    n: int | None
    heldout: dict[str, Any] | None = None
    scorecard: dict[str, Any] | None = None
    why_not: str = ""  # why the version has no usable run
    started_at: str | None = None  # the winning run's start, for the challenger tie-break
    pass_at_1: float | None = None  # the leaderboard's number (s11); it leads the rule (D46)
    gate: str = ""  # why the leak gate bars it from taking the title (D46); "" when it may

    @property
    def sql_passed(self) -> int:
        """SQL passed of the questions with a golden; -1 when the run has no statement to score."""
        sql = (self.scorecard or {}).get("sql") or {}
        return int(sql["passed"]) if sql.get("n") else -1


def candidate(version: str) -> Candidate:
    from dab_bench.eval.runner import list_runs
    from dab_bench.eval.scorecard import load_scorecard

    runs = [
        m
        for m in list_runs()
        if m.agent == version and m.split == "all" and not m.dry_run and m.summary
    ]
    if not runs:
        return Candidate(version, None, None, None, None, why_not="no full-split run")
    m = max(runs, key=lambda r: r.started_at)
    s = m.summary or {}
    if s.get("scored") != s.get("n") or s.get("rate_limited"):
        return Candidate(
            version,
            m.run_id,
            s.get("passed"),
            s.get("scored"),
            s.get("n"),
            why_not=f"{s.get('n', 0) - s.get('scored', 0)} trial(s) not scored: `dab eval --resume {m.run_id}`",
            started_at=m.started_at,
        )
    card = load_scorecard(m.run_id)
    return Candidate(
        version,
        m.run_id,
        int(s["passed"]),
        int(s["scored"]),
        int(s["n"]),
        heldout=((card or {}).get("by_split") or {}).get("heldout"),
        scorecard=(card or {}).get("totals"),
        started_at=m.started_at,
        pass_at_1=s.get("pass_rate_macro"),
    )


# ── the leak gate (D46) ─────────────────────────────────────────────────────

LEAK_GUARDS = ("literal", "g1_review", "g2_audit", "g3_breadth", "g4_routing")


def _unguarded(version: str, agents_dir: Path) -> str:
    """Why `version` was not made under guards G1–G4, or "": the round that made it recorded
    every guard on; a model switch (`measured_against`, no round) is judged
    by the version it copied; a base version (neither) was written with no gold in sight."""
    seen: set[str] = set()
    v: str | None = version
    while v and v not in seen:
        seen.add(v)
        d = agents_dir / v
        if (d / "optimise.json").exists():
            on = json.loads((d / "optimise.json").read_text()).get("guards") or {}
            if all(on.get(g) for g in LEAK_GUARDS):
                return ""
            where = "" if v == version else f" (its text is {v}'s)"
            return f"its round ran without guards G1–G4{where}; `dab optimise --strict` runs them"
        cfg = d / "agent.yaml"
        v = (
            (yaml.safe_load(cfg.read_text()) or {}).get("measured_against")
            if cfg.exists()
            else None
        )
    return ""


def _golds() -> list[tuple[str, str]]:
    from dab_bench.data.index import load

    return [
        (q["question"], q.get("gold_text") or "") for q in load().queries if q.get("released", True)
    ]


def leak_gate(
    version: str,
    agents_dir: Path = AGENTS_DIR,
    golds: Iterable[tuple[str, str]] | None = None,
) -> str:
    """D46: why `version` may not take the title, or "" when it passes the leak gate: the round
    that made it ran guards G1–G4, and G2 finds no gold value in its `system.md` or any
    dataset's notes (counts only; the values never reach the record)."""
    from dab_bench.eval.guards import audit

    if why := _unguarded(version, agents_dir):
        return why
    d = agents_dir / version
    units = {"system.md": (d / "system.md").read_text()} | {
        f"notes:{ds}": t for ds, t in load_notes(d).items()
    }
    if hits := audit(units, _golds() if golds is None else golds):
        return f"G2: {sum(hits.values())} gold value(s) in {', '.join(sorted(hits))}"
    return ""


# ── the rule ────────────────────────────────────────────────────────────────

RULE = (
    "D46: a challenger takes the title only through the leak gate (its round ran guards "
    "G1–G4, no gold value in its prompt); the highest Pass@1 wins; answers passed of the "
    "54 break a tie, then SQL passed of the questions with a golden; then the incumbent; then "
    "the older run"
)


def _line(c: Candidate) -> str:
    sql = (c.scorecard or {}).get("sql") or {}
    s = f"SQL {sql['passed']}/{sql['n']}" if sql.get("n") else "no SQL"
    p = f"Pass@1 {c.pass_at_1:.3f} · " if c.pass_at_1 is not None else ""
    return f"{c.version} {p}answers {c.passed}/{c.scored} · {s}"


def _key(c: Candidate) -> tuple[float, int, int]:
    p = round(c.pass_at_1, 9) if c.pass_at_1 is not None else -1.0
    return (p, c.passed or 0, c.sql_passed)


def decide(cands: list[Candidate], incumbent: str) -> tuple[str, str]:
    """(winner, reason) by D46: challengers barred by the leak gate stand aside; then the
    highest Pass@1; then the most answers passed; then the most SQL passed; a tie on all three
    keeps the incumbent; a tie between two challengers goes to whichever's run started first."""
    runs = [c for c in cands if not c.why_not and c.passed is not None]
    barred = [c for c in runs if c.gate and c.version != incumbent]
    ok = [c for c in runs if c not in barred]
    if not ok:
        return incumbent, "no candidate has a complete full-split run; the incumbent stays"
    best = max(_key(c) for c in ok)
    top = [c for c in ok if _key(c) == best]
    names = "; ".join(_line(c) for c in ok)
    if barred:
        names += "; barred by the leak gate: " + ", ".join(c.version for c in barred)
    if len([c for c in ok if _key(c)[0] == best[0]]) == 1:
        decided_by = "the highest Pass@1"
    elif len([c for c in ok if _key(c)[:2] == best[:2]]) == 1:
        decided_by = "answers break the tie on Pass@1"
    else:
        decided_by = "SQL breaks the tie on Pass@1 and answers"
    tie = len(top) > 1
    if any(c.version == incumbent for c in top):
        return incumbent, (
            f"{incumbent} keeps the title: "
            + ("a tie on Pass@1, answers and SQL keeps the incumbent" if tie else decided_by)
            + f" ({names})"
        )
    winner = min(top, key=lambda c: c.started_at or "")
    return winner.version, (
        f"{winner.version} wins: "
        + ("a tie on Pass@1, answers and SQL, broken by the older run" if tie else decided_by)
        + f" ({names})"
    )


def promote(candidates: list[str] | None = None, dry_run: bool = False) -> dict[str, Any]:
    incumbent = champion_name()
    names = candidates or list_versions()
    for v in names:
        load_version(v)  # a typo fails here, not as "no run"
    cands = [candidate(v) for v in names]
    golds = _golds()
    for c in cands:
        c.gate = leak_gate(c.version, golds=golds)
    winner, reason = decide(cands, incumbent)
    record: dict[str, Any] = {
        "at": datetime.now(UTC).isoformat(),
        "rule": RULE,
        "incumbent": incumbent,
        "winner": winner,
        "changed": winner != incumbent,
        "reason": reason,
        "candidates": [asdict(c) for c in cands],
        "champion_run_id": next((c.run_id for c in cands if c.version == winner), None),
    }
    if dry_run:
        return record | {"dry_run": True}
    try:
        from dab_bench.tracking.prompts import register, set_champion

        pv = register(load_version(winner))
        set_champion(pv)
        record["prompt_version"] = pv
    except Exception as e:  # noqa: BLE001 - the pointer file is the record; the alias an index
        record["prompt_error"] = f"{type(e).__name__}: {e}"
    if record["changed"]:
        CHAMPION_FILE.write_text(winner + "\n")
    with PROMOTIONS.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    try:  # s13 (B2): the index; promotions.jsonl above is the record
        from dab_bench.eval.outcome import log_all

        record["outcomes"] = log_all([c.version for c in cands])
    except Exception as e:  # noqa: BLE001
        record["outcomes_error"] = f"{type(e).__name__}: {e}"
    return record


def champion_run() -> str | None:
    """The champion's newest complete full-split run: where a round starts (s13)."""
    c = candidate(champion_name())
    return c.run_id if c.run_id and not c.why_not else None


def history() -> list[dict[str, Any]]:
    if not PROMOTIONS.exists():
        return []
    return [json.loads(line) for line in PROMOTIONS.read_text().splitlines() if line.strip()]
