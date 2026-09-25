"""`dab promote`: the champion is the version whose statements are right most often (D36).

Each candidate version is represented by its newest complete run of the full split: not a
dry run, every trial scored (a rate-limited trial must be resumed first). The rule (plan
s08, D36, replacing D30's answers-only rule): the most **SQL passed** of the questions
with a golden (the re-run statement returns the golden's rows) wins; the most **answers
passed** of the 54 (the leaderboard's number) breaks a tie; a tie on both keeps the
incumbent; a tie between two challengers goes to whichever's newest complete full-split
run started first (the older run). A version without a statement to score (v0) counts as
no SQL passed. The verdict appends to `agents/promotions.jsonl`, with the rule's name,
every candidate's top lines, its scorecard and its held-out result, and `agents/champion`
moves when the winner changes. The winner's prompt gets the `champion` alias in the MLflow
prompt registry.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from dab_bench.agent.versions import CHAMPION_FILE, champion_name, list_versions, load_version
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
    )


RULE = (
    "D36: the most SQL passed of the questions with a golden wins; answers passed of the 54 "
    "break a tie; then the incumbent; then the older run"
)


def _line(c: Candidate) -> str:
    sql = (c.scorecard or {}).get("sql") or {}
    s = f"SQL {sql['passed']}/{sql['n']}" if sql.get("n") else "no SQL"
    return f"{c.version} {s} · answers {c.passed}/{c.scored}"


def decide(cands: list[Candidate], incumbent: str) -> tuple[str, str]:
    """(winner, reason) by D36: the most SQL passed; then the most answers passed; a tie on both
    keeps the incumbent; a tie between two challengers goes to whichever's run started first."""
    ok = [c for c in cands if not c.why_not and c.passed is not None]
    if not ok:
        return incumbent, "no candidate has a complete full-split run; the incumbent stays"

    def key(c: Candidate) -> tuple[int, int]:
        return (c.sql_passed, c.passed or 0)

    best = max(key(c) for c in ok)
    top = [c for c in ok if key(c) == best]
    by_sql = [c for c in ok if c.sql_passed == best[0]]
    names = "; ".join(_line(c) for c in ok)
    decided_by = "answers break the tie on SQL" if len(by_sql) > 1 else "the most SQL passed"
    if any(c.version == incumbent for c in top):
        tie = len(top) > 1
        return incumbent, (
            f"{incumbent} keeps the title: "
            + ("a tie on SQL and answers keeps the incumbent" if tie else decided_by)
            + f" ({names})"
        )
    winner = min(top, key=lambda c: c.started_at or "")
    tie = len(top) > 1
    return winner.version, (
        f"{winner.version} wins: "
        + ("a tie on SQL and answers, broken by the older run" if tie else decided_by)
        + f" ({names})"
    )


def promote(candidates: list[str] | None = None, dry_run: bool = False) -> dict[str, Any]:
    incumbent = champion_name()
    names = candidates or list_versions()
    for v in names:
        load_version(v)  # a typo fails here, not as "no run"
    cands = [candidate(v) for v in names]
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
    return record


def history() -> list[dict[str, Any]]:
    if not PROMOTIONS.exists():
        return []
    return [json.loads(line) for line in PROMOTIONS.read_text().splitlines() if line.strip()]
