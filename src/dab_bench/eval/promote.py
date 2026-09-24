"""`dab promote`: the champion is the version with the best answer accuracy on the 54 (D30).

Each candidate version is represented by its newest complete run of the full split: not a
dry run, every trial scored (a rate-limited trial must be resumed first). Accuracy is the
top line, answers passed out of trials scored, the leaderboard's own number. The most
answers passed wins; a tie keeps the incumbent, and a tie between two challengers goes
to the one listed first (the older version). The verdict appends to
`agents/promotions.jsonl`, with every candidate's top line, its scorecard and its
held-out result, and `agents/champion` moves when the winner changes. The winner's
prompt gets the `champion` alias in the MLflow prompt registry.
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
    )


def decide(cands: list[Candidate], incumbent: str) -> tuple[str, str]:
    """(winner, reason): the most answers passed; a tie keeps the incumbent."""
    ok = [c for c in cands if not c.why_not and c.passed is not None]
    if not ok:
        return incumbent, "no candidate has a complete full-split run; the incumbent stays"
    best = max(c.passed or 0 for c in ok)
    top = [c for c in ok if c.passed == best]
    names = ", ".join(f"{c.version} {c.passed}/{c.scored}" for c in ok)
    if any(c.version == incumbent for c in top):
        tie = len(top) > 1
        return incumbent, (
            f"{incumbent} keeps the title: "
            + ("a tie at the top keeps the incumbent" if tie else "it has the best top line")
            + f" ({names})"
        )
    return top[0].version, f"{top[0].version} has the best top line ({names})"


def promote(candidates: list[str] | None = None, dry_run: bool = False) -> dict[str, Any]:
    incumbent = champion_name()
    names = candidates or list_versions()
    for v in names:
        load_version(v)  # a typo fails here, not as "no run"
    cands = [candidate(v) for v in names]
    winner, reason = decide(cands, incumbent)
    record: dict[str, Any] = {
        "at": datetime.now(UTC).isoformat(),
        "rule": "D30: the most answers passed of the 54 wins; a tie keeps the incumbent",
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
