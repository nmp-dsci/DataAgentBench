"""Optimisation rounds and the champion's history, as the explorer reads them.

A **round** is one `dab optimise <run> --into <version>`: it read a scored run (the
*diagnostic*), wrote a new version (the *proposal*, `agents/<version>/`), and that
version's newest complete full-split run is its *outcome*. Rounds chain: the outcome
of one can be the diagnostic of the next, so the list is a lineage over time.

The outcome is read the way an experiment comparison reads two runs (a baseline and a
candidate, per example): every question before and after, improved / regressed /
unchanged, per split, per dataset, and how failure categories moved.

The **champion's history** is the reigns `dab promote` recorded
(`agents/promotions.jsonl`): who held the title from when, on which run, with what
top line, and the lift over the reign before. Everything here is read from the run
folders and the agent folders; nothing calls a model or writes.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from dab_bench.config import AGENTS_DIR, RUNS_DIR


def _load(path: Any) -> Any:
    return json.loads(path.read_text()) if path.exists() else None


def round_records() -> list[dict[str, Any]]:
    """Every version an optimisation round wrote, oldest round first (a `dab crossfit` fold is
    a measurement, not a round: left out)."""
    recs = []
    for p in sorted(AGENTS_DIR.glob("*/optimise.json")):
        rec = json.loads(p.read_text())
        if rec.get("crossfit"):
            continue
        rec.setdefault("version", p.parent.name)
        recs.append(rec)
    return sorted(recs, key=lambda r: str(r.get("started_at") or ""))


def header_note(agent_yaml: Path) -> str:
    """The version's own line from the comment block atop its `agent.yaml` (each version
    prepends its line to its source's block, so the first block is its own)."""
    if not agent_yaml.exists():
        return ""
    lines: list[str] = []
    for raw in agent_yaml.read_text().splitlines():
        if not raw.startswith("#"):
            break
        text = raw.lstrip("#").strip()
        if lines and re.match(r"v\w+\s*[:—]", text):
            break
        lines.append(text)
    return " ".join(lines)


def version_change(
    config: Any, source: Any | None, rec: dict[str, Any] | None, round_no: int | None
) -> dict[str, Any]:
    """How a version was made from the one before it: an optimisation round (`challenger_of`),
    a model change (the same prompt files on another model), a build change (anything else
    hand-built: the tools, the answer contract, the hints), or the base. `config` and `source`
    are `AgentConfig`s; `rec` is the version's round record."""
    if rec is not None:
        g = rec.get("guards") or {}
        strict = all(g.get(k) for k in ("g1_review", "g2_audit", "g3_breadth", "g4_routing"))
        detail = f"round {round_no}" + (" · G1–G4" if strict else "")
        return {"kind": "round", "detail": detail}
    if source is None:
        return {"kind": "base", "detail": "the first build"}
    if source.model != config.model:
        return {"kind": "model", "detail": f"{source.model} → {config.model}"}
    sql = "mcp__dab__submit_answer"
    if (sql in source.tools) != (sql in config.tools):
        detail = "SQL answer" if sql in config.tools else "free answer"
    elif len(source.tools) != len(config.tools):
        detail = f"{len(source.tools)} → {len(config.tools)} tools"
    elif source.hints != config.hints:
        detail = "hints on" if config.hints else "hints off"
    elif source.pack != config.pack:
        detail = "pack on" if config.pack else "pack off"
    else:
        detail = "hand-built"
    return {"kind": "build", "detail": detail}


def _results(run_id: str) -> dict[str, dict[str, Any]]:
    p = RUNS_DIR / run_id / "results.jsonl"
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if r["trial"] == 1:
                out[r["query_id"]] = r
    return out


def _card_rows(run_id: str) -> dict[str, dict[str, Any]]:
    card = _load(RUNS_DIR / run_id / "scorecard.json") or {}
    return {q["query_id"]: q for q in card.get("questions", []) if q["trial"] == 1}


def outcome_run(version: str) -> str | None:
    """The version's newest complete full-split run (the one `dab promote` would read)."""
    from dab_bench.eval.promote import candidate

    c = candidate(version)
    return None if c.why_not else c.run_id


def _side(r: dict[str, Any] | None, s: dict[str, Any] | None) -> dict[str, Any] | None:
    if r is None:
        return None
    s = s or {}
    led = s.get("ledger") or {}
    return {
        "answer": r.get("passed"),
        "sql": s.get("sql"),
        "decision": s.get("decision"),
        "category": s.get("category", ""),
        "mode": r.get("mode"),
        # the ledger (s08): where the statement breaks, a verdict per step, the lines in words
        "breaks_at": s.get("breaks_at"),
        "why": led.get("why") or "",
        "verdicts": led.get("verdicts"),
        "golden_lines": led.get("golden"),
        "agent_lines": led.get("agent"),
        "plan": r.get("plan"),
    }


def change(before: bool | None, after: bool | None) -> str:
    """improved / regressed / held (pass both) / still failing / not scored."""
    if before is None or after is None:
        return "not scored"
    if after and not before:
        return "improved"
    if before and not after:
        return "regressed"
    return "held" if after else "still failing"


def compare_questions(
    before_run: str,
    after_run: str | None,
    split: dict[str, list[str]] | None,
    read: set[str],
) -> list[dict[str, Any]]:
    """Every question of the diagnostic run beside the outcome run."""
    br, bc = _results(before_run), _card_rows(before_run)
    ar, ac = (_results(after_run), _card_rows(after_run)) if after_run else ({}, {})
    where = {q: name for name, qs in (split or {}).items() for q in qs}
    rows = []
    for qid, r in br.items():
        b = _side(r, bc.get(qid))
        a = _side(ar.get(qid), ac.get(qid)) if after_run else None
        rows.append(
            {
                "query_id": qid,
                "dataset": r["dataset"],
                "question": r["question"],
                "split": where.get(qid)
                or ("no golden" if bc.get(qid, {}).get("golden_id") is None else None),
                "read": qid in read,  # the optimiser was shown this question
                "before": b,
                "after": a,
                "change": change(b["answer"] if b else None, a["answer"] if a else None),
                "sql_change": change(b["sql"] if b else None, a["sql"] if a else None),
            }
        )
    return rows


def summarise_changes(rows: list[dict[str, Any]]) -> dict[str, Any]:
    kinds = ("improved", "regressed", "held", "still failing", "not scored")

    def tally(rs: list[dict[str, Any]]) -> dict[str, Any]:
        c = Counter(r["change"] for r in rs)
        before = sum(1 for r in rs if r["before"] and r["before"]["answer"])
        after = sum(1 for r in rs if r["after"] and r["after"]["answer"])
        # the statement, over the questions with a golden (s08: the round's target)
        gs = [r for r in rs if r["before"] and r["before"].get("sql") is not None]
        cs = Counter(r.get("sql_change", "not scored") for r in gs)
        sql = {
            "n": len(gs),
            "before": sum(1 for r in gs if r["before"]["sql"]),
            "after": sum(1 for r in gs if r["after"] and r["after"].get("sql")),
        } | {k: cs.get(k, 0) for k in kinds}
        return {"n": len(rs), "before": before, "after": after, "sql": sql} | {
            k: c.get(k, 0) for k in kinds
        }

    splits = sorted({str(r["split"]) for r in rows if r["split"]})
    by_ds: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_ds.setdefault(r["dataset"], []).append(r)
    moves: Counter[tuple[str, str]] = Counter()
    for r in rows:
        if r["before"] and r["after"]:
            moves[(r["before"]["category"] or "—", r["after"]["category"] or "—")] += 1
    return {
        "all": tally(rows),
        "by_split": {s: tally([r for r in rows if r["split"] == s]) for s in splits},
        "by_dataset": {d: tally(rs) for d, rs in sorted(by_ds.items())},
        "category_moves": [
            {"from": f, "to": t, "n": n}
            for (f, t), n in sorted(moves.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
    }


def _totals(run_id: str | None) -> dict[str, Any] | None:
    if not run_id:
        return None
    card = _load(RUNS_DIR / run_id / "scorecard.json")
    meta = _load(RUNS_DIR / run_id / "run.json") or {}
    return (
        None
        if card is None
        else {
            "totals": card["totals"],
            "by_split": card.get("by_split"),
            # the leaderboard's number (s11): mean over datasets of each one's pass rate
            "pass_at_1": (meta.get("summary") or {}).get("pass_rate_macro"),
        }
    )


def read_all(rec: dict[str, Any]) -> bool:
    """The round read every error of the 54 (s11, D38): no question was held out."""
    return rec.get("trained_on") == "all"


def session_kind(s: dict[str, Any]) -> str:
    """dataset | component | system; round-1 records carry no `kind`."""
    if s.get("kind"):
        return str(s["kind"])
    return "system" if s["scope"] == "system.md" else "dataset"


def attempts(s: dict[str, Any]) -> list[dict[str, Any]]:
    """Every write a session made, in order. A round-1 record keeps only its refusals and the
    accepted text, so its attempts are the refusals then, when notes were kept, one accepted."""
    if s.get("attempts") is not None:
        return list(s["attempts"])
    out = [
        {"ok": False, "chars": r.get("notes_chars"), "problems": r.get("problems") or []}
        for r in s.get("refusals") or []
    ]
    if s.get("notes") is not None:
        out.append({"ok": True, "chars": len(s["notes"] or ""), "problems": []})
    return out


def _is_leak(problem: str) -> bool:
    from dab_bench.eval.guards import is_leak

    return is_leak(problem)


def stages(
    rec: dict[str, Any], after: str | None, promoted: dict[str, Any] | None
) -> dict[str, Any]:
    """The round as the loop figure draws it: the counts on each of the seven stages."""
    before = _load(RUNS_DIR / rec["source_run"] / "scorecard.json") or {}
    src_meta = _load(RUNS_DIR / rec["source_run"] / "run.json") or {}
    out_card = _load(RUNS_DIR / after / "scorecard.json") if after else None
    qs = [q for q in before.get("questions", []) if q["trial"] == 1]
    sessions = rec.get("sessions", [])
    writes = [a for s in sessions for a in attempts(s)]
    kinds = Counter(session_kind(s) for s in sessions)
    read = {q for s in sessions for q in s.get("questions") or []}
    breaks = Counter(q.get("breaks_at") for q in qs if q.get("breaks_at"))
    target = AGENTS_DIR / rec["version"]
    return {
        "run": {
            "agent": rec.get("challenger_of"),
            "run_id": rec["source_run"],
            "trials": len(qs),
            "totals": before.get("totals"),
            "cost_usd": (src_meta.get("summary") or {}).get("cost_usd"),
        },
        "diagnose": {
            "goldened": sum(1 for q in qs if q.get("golden_id") is not None),
            "sql_fails": sum(1 for q in qs if q.get("sql") is False),
            "ledger": any(q.get("ledger") for q in qs),
            "breaks": dict(breaks),
            "categories": before.get("categories", {}),
        },
        "split": {
            "sizes": rec.get("split"),
            "read": len(read),
            "heldout_sql": None
            if read_all(rec)
            else ((before.get("by_split") or {}).get("heldout") or {}).get("sql"),
            "read_all": read_all(rec),
        },
        "sessions": {
            "dataset": kinds.get("dataset", 0),
            "component": kinds.get("component", 0),
            "system": kinds.get("system", 0),
            "cost_usd": rec.get("cost_usd"),
            "model": (rec.get("optimiser") or {}).get("model"),
        },
        "guard": {
            "writes": len(writes),
            "refused": sum(1 for a in writes if not a["ok"]),
            "leaks": sum(1 for a in writes if any(_is_leak(p) for p in a["problems"])),
            "too_long": sum(1 for a in writes if any(not _is_leak(p) for p in a["problems"])),
            "accepted": sum(1 for s in sessions if s.get("notes") is not None),
            "dropped": sum(1 for s in sessions if s.get("dropped")),
            "caps": rec.get("caps"),
        },
        "version": {
            "name": rec["version"],
            "notes": sum(1 for s in sessions if session_kind(s) == "dataset" and s.get("notes")),
            "sections": sum(
                1 for s in sessions if session_kind(s) == "component" and s.get("notes")
            ),
            "system_md_chars": len((target / "system.md").read_text())
            if (target / "system.md").exists()
            else None,
            "system_md_changed": rec.get("system_md_changed"),
            "plan_first": rec.get("plan_first", False),
            "fingerprint": rec.get("fingerprint"),
            "prompt_version": rec.get("prompt_version"),
        },
        "outcome": {
            "run_id": after,
            "totals": (out_card or {}).get("totals"),
            "heldout_sql": None
            if read_all(rec)
            else (((out_card or {}).get("by_split") or {}).get("heldout") or {}).get("sql"),
            "promoted_at": promoted["at"] if promoted else None,
        },
    }


def round_summary(rec: dict[str, Any]) -> dict[str, Any]:
    """One row of the rounds list: what it read, what it wrote, what it scored."""
    from dab_bench.eval.promote import history

    after = outcome_run(rec["version"])
    sessions = [s for s in rec.get("sessions", []) if session_kind(s) != "system"]
    rows = compare_questions(rec["source_run"], after, None, set())
    tally = summarise_changes(rows)["all"]
    promoted = next(
        (p for p in history() if p.get("winner") == rec["version"] and p.get("changed")), None
    )
    return {
        "version": rec["version"],
        "parent": rec.get("challenger_of"),
        "source_run": rec["source_run"],
        "outcome_run": after,
        "started_at": rec.get("started_at"),
        "optimiser": rec.get("optimiser"),
        "cost_usd": rec.get("cost_usd"),
        "sessions": len(sessions),
        "notes_written": sum(
            1 for s in sessions if s.get("notes") and session_kind(s) == "dataset"
        ),
        "sections_written": sum(
            1 for s in sessions if s.get("notes") and session_kind(s) == "component"
        ),
        "method": rec.get("method")
        or "dataset sessions + a cross-dataset system.md pass (s06, D31 A)",
        "plan_first": rec.get("plan_first", False),
        "refusals": sum(len(s.get("refusals") or []) for s in rec.get("sessions", [])),
        "system_md_changed": rec.get("system_md_changed"),
        "split": rec.get("split"),
        "trained_on": rec.get("trained_on") or "train",
        "guards": rec.get("guards"),
        "before": _totals(rec["source_run"]),
        "after": _totals(after),
        "changes": tally,
        "promoted_at": promoted["at"] if promoted else None,
        "stages": stages(rec, after, promoted),
    }


def round_detail(version: str) -> dict[str, Any] | None:
    from dab_bench.eval.scorecard import load_optimise_split

    rec = _load(AGENTS_DIR / version / "optimise.json")
    if rec is None:
        return None
    rec.setdefault("version", version)
    # a round that read every error has no held-out questions to label (s11)
    split = None if read_all(rec) else load_optimise_split()
    read = {q for s in rec.get("sessions", []) for q in s.get("questions") or []}
    after = outcome_run(version)
    rows = compare_questions(rec["source_run"], after, split, read)
    card = _load(RUNS_DIR / rec["source_run"] / "scorecard.json") or {}
    from dab_bench.eval.ledger import COMPONENTS, WHAT

    return {
        "summary": round_summary(rec),
        "components": [{"name": c, "what": WHAT[c]} for c in COMPONENTS],
        "record": rec,
        "diagnostic": {
            "run_id": rec["source_run"],
            "totals": card.get("totals"),
            "by_split": card.get("by_split"),
            "optimise_first": card.get("optimise_first", []),
            "categories": card.get("categories", {}),
        },
        "questions": rows,
        "outcome": summarise_changes(rows) if after else None,
    }


# ── the champion over time ───────────────────────────────────────────────────


def champion_history() -> dict[str, Any]:
    """The reigns (who held the title from when, its top line, the lift) and every full-split
    run as a point, for the Runs tab's accuracy-over-time figure."""
    from dab_bench.agent.versions import champion_name
    from dab_bench.eval.promote import history
    from dab_bench.eval.runner import list_runs

    runs = [
        m
        for m in list_runs()
        if m.split == "all" and not m.dry_run and m.summary and m.summary.get("scored")
    ]
    points = [
        {
            "run_id": m.run_id,
            "agent": m.agent,
            "started_at": m.started_at,
            "passed": int((m.summary or {})["passed"]),
            "scored": int((m.summary or {})["scored"]),
        }
        for m in sorted(runs, key=lambda m: m.started_at)
    ]
    by_run = {p["run_id"]: p for p in points}
    reigns: list[dict[str, Any]] = []
    promos = history()
    if promos:
        first = promos[0]
        inc = next((c for c in first["candidates"] if c["version"] == first["incumbent"]), None)
        if inc and inc.get("run_id") in by_run:
            p = by_run[inc["run_id"]]
            reigns.append(
                {
                    "version": first["incumbent"],
                    "run_id": p["run_id"],
                    "from": p["started_at"],
                    "passed": p["passed"],
                    "scored": p["scored"],
                    "reason": "the first champion",
                }
            )
    for pr in promos:
        if not pr.get("changed"):
            continue
        run = pr.get("champion_run_id")
        won = by_run.get(run) if run else None
        if won is None:
            continue
        p = won
        reigns.append(
            {
                "version": pr["winner"],
                "run_id": run,
                "from": pr["at"],
                "passed": p["passed"],
                "scored": p["scored"],
                "reason": pr.get("reason", ""),
            }
        )
    if not reigns:
        champ = champion_name()
        mine = [p for p in points if p["agent"] == champ]
        if mine:
            p = mine[0]
            reigns.append(
                {
                    "version": champ,
                    "run_id": p["run_id"],
                    "from": p["started_at"],
                    "passed": p["passed"],
                    "scored": p["scored"],
                    "reason": "the first champion",
                }
            )
    for i, r in enumerate(reigns):
        prev = reigns[i - 1] if i else None
        r["lift"] = None if prev is None else r["passed"] - prev["passed"]
        r["until"] = reigns[i + 1]["from"] if i + 1 < len(reigns) else None
    return {"reigns": reigns, "points": points, "promotions": promos}
