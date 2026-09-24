"""The scorecard (plan s06): every question of a run scored three times, and why it failed.

- **answer**: the question's own validator on the submitted answer, the leaderboard's
  number. Every question has it; the denominator is the run's scored trials (54).
- **SQL**: the agent's result against the golden's result. The agent's SQL and the
  golden are both re-run as `dab_agent`, and the rows compared with the gold match's cell
  rules (case, float noise in the last digit; a numeric column at the fewer decimal places
  of the two sides), in any row order. Columns are matched by
  their values, so column order and names do not matter, and extra agent columns are
  allowed. An evidence golden passes when the agent's rows contain the golden's. Only where
  a golden exists.
- **decision**: the mode the agent chose against the golden's kind. An answer golden
  says the result is the answer (`pass_through`); an evidence golden says a reading
  step is needed (`derived`). Only where a golden exists.

Each trial then gets one **category**, the first that applies: no golden · no SQL ·
SQL error · (SQL passes) decision, derived step wrong, format · (SQL fails) right answer
another way, then the first structural difference `sqlglot` finds between the two
statements: wrong tables, join differs, parse differs, filter differs, aggregation,
order / tie, else result differs. The categories are what the optimiser works down.

The scorecard reads goldens from `dataagentbench_meta` as `dab_owner`, and it is
computed after the run: nothing in it ever reaches a trial. It writes
`runs/<id>/scorecard.json` beside `results.jsonl`, without the golden SQL text (the
explorer and the optimiser read that from the database).

The train / held-out split the optimiser uses (D29–D30) is fixed here too:
`data/splits/train.json` and `heldout.json`, 2/3 of each dataset's goldened questions
for training, seeded, written once and committed.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp

from dab_bench.config import RUNS_DIR, SPLITS_DIR

SEED = 20260924
TRAIN_SHARE = 2 / 3
MODE_FOR_KIND = {"answer": "pass_through", "evidence": "derived"}
DIFF_LINES = 200

# the categories, in the order they are tested; `solved` is not a failure
CATEGORIES = (
    "no golden",
    "no SQL",
    "SQL error",
    "decision",
    "derived step wrong",
    "format",
    "right answer another way",
    "wrong tables",
    "join differs",
    "parse differs",
    "filter differs",
    "aggregation",
    "order / tie",
    "result differs",
)
NOT_OPTIMISED = ("solved", "no golden", "right answer another way")


# ── the optimiser's split ─────────────────────────────────────────────────────


def make_split(goldened: list[str], seed: int = SEED) -> dict[str, list[str]]:
    """2/3 of each dataset's goldened questions for training (at least one held out)."""
    by_ds: dict[str, list[str]] = {}
    for q in sorted(goldened):
        by_ds.setdefault(q.split("/")[0], []).append(q)
    rng = random.Random(seed)
    train: list[str] = []
    heldout: list[str] = []
    for ds in sorted(by_ds):
        qs = by_ds[ds][:]
        rng.shuffle(qs)
        n = len(qs)
        k = n if n == 1 else max(1, min(n - 1, round(n * TRAIN_SHARE)))
        train += qs[:k]
        heldout += qs[k:]
    order = _index_order()
    return {"train": sorted(train, key=order), "heldout": sorted(heldout, key=order)}


def _index_order() -> Any:
    ds_n = {}
    with suppress(Exception):
        from dab_bench.eval.splits import all_queries

        ds_n = {q.id: i for i, q in enumerate(all_queries())}
    return lambda q: ds_n.get(q, 10_000)


def write_split(goldened: list[str], splits_dir: Path = SPLITS_DIR) -> dict[str, list[str]]:
    split = make_split(goldened)
    rule = (
        f"seed {SEED}; per dataset, round(2/3) of the questions with a golden train the "
        "optimiser, the rest are held out (at least one each); written once from the goldens "
        "of the day and never re-drawn, so every version is measured on the same split"
    )
    for name in ("train", "heldout"):
        (splits_dir / f"{name}.json").write_text(
            json.dumps({"queries": split[name], "rule": rule, "seed": SEED}, indent=1) + "\n"
        )
    return split


def load_optimise_split(splits_dir: Path = SPLITS_DIR) -> dict[str, list[str]] | None:
    out = {}
    for name in ("train", "heldout"):
        p = splits_dir / f"{name}.json"
        if not p.exists():
            return None
        out[name] = list(json.loads(p.read_text())["queries"])
    return out


# ── comparing two results ───────────────────────────────────────────────────


def _key(v: Any) -> str:
    """A cell as the gold match compares it: trimmed, lower case, numbers to 9 significant digits."""
    from dab_bench.eval.golden import _text

    s = _text(v).strip().lower()
    with suppress(ValueError):
        return f"{float(s):.9g}"
    return s


def _decimals(values: list[Any]) -> int | None:
    """The most decimal places in a column of numbers; None when any value is not a number."""
    most = 0
    for v in values:
        if isinstance(v, bool) or not isinstance(v, int | float | str):
            return None
        s = str(v).strip()
        try:
            float(s)
        except ValueError:
            return None
        if "e" in s.lower():
            return None
        most = max(most, len(s.split(".", 1)[1]) if "." in s else 0)
    return most


def _pair_key(g_vals: list[Any], a_vals: list[Any]) -> Any:
    """How to compare one golden column with one agent column: both numeric, at the fewer
    decimal places of the two (an agent's 3.55 is the golden's 3.547008…, as a validator
    reads it); otherwise the gold match's cell rule."""
    dg, da = _decimals(g_vals), _decimals(a_vals)
    if dg is None or da is None or dg == da:
        return _key
    d = min(dg, da)
    return lambda v: f"{round(float(v), d):.{d}f}"


def _match_columns(
    g_rows: list[list[Any]], a_rows: list[list[Any]], gw: int, aw: int, contain: bool
) -> list[tuple[int, Any]] | None:
    """For each golden column, an agent column with the same values (or, `contain`, a
    superset), and the key the pair compares with."""
    used: set[int] = set()
    out = []
    for j in range(gw):
        gv = [r[j] for r in g_rows]
        pick = None
        for k in range(aw):
            if k in used:
                continue
            av = [r[k] for r in a_rows]
            key = _pair_key(gv, av)
            gc, ac = Counter(key(v) for v in gv), Counter(key(v) for v in av)
            if (not (gc - ac)) if contain else gc == ac:
                pick = (k, key)
                break
        if pick is None:
            return None
        used.add(pick[0])
        out.append(pick)
    return out


def compare_results(
    g_cols: list[str],
    g_rows: list[list[Any]],
    a_cols: list[str],
    a_rows: list[list[Any]],
    kind: str,
) -> dict[str, Any]:
    """Does the agent's result recreate the golden's? {"pass": bool, "detail": str}."""
    contain = kind == "evidence"
    if not a_rows:
        return {"pass": False, "detail": "the agent's SQL returned no rows"}
    if not contain and len(a_rows) != len(g_rows):
        return {"pass": False, "detail": f"{len(a_rows)} row(s) against the golden's {len(g_rows)}"}
    cols = _match_columns(g_rows, a_rows, len(g_cols), len(a_cols), contain=contain)
    if cols is None:
        return {
            "pass": False,
            "detail": "no agent column holds the values of every golden column",
        }
    g_set = Counter(tuple(key(r[j]) for j, (_, key) in enumerate(cols)) for r in g_rows)
    a_set = Counter(tuple(key(r[k]) for k, key in cols) for r in a_rows)
    extra = len(a_cols) - len(g_cols)
    if contain:
        missing = g_set - a_set
        if missing:
            return {
                "pass": False,
                "detail": f"{sum(missing.values())} of the golden's {len(g_rows)} evidence row(s) missing",
            }
        return {"pass": True, "detail": f"contains the golden's {len(g_rows)} evidence row(s)"}
    if g_set != a_set:
        n = sum((g_set - a_set).values())
        return {"pass": False, "detail": f"{n} of {len(g_rows)} row(s) differ from the golden's"}
    rounded = any(key is not _key for _, key in cols)
    return {
        "pass": True,
        "detail": f"the golden's {len(g_rows)} row(s)"
        + (", compared at the agent's rounding" if rounded else "")
        + (f", plus {extra} extra column(s)" if extra > 0 else ""),
    }


# ── the structure of a statement ────────────────────────────────────────────


def _is_in(node: exp.Expression, kinds: tuple[type[exp.Expression], ...]) -> bool:
    p = node.parent
    while p is not None:
        if isinstance(p, kinds):
            return True
        p = p.parent
    return False


_PATTERN_FUNCS = {
    "regexp_match",
    "regexp_matches",
    "regexp_replace",
    "regexp_substr",
    "substring",
    "split_part",
    "regexp_split_to_array",
    "regexp_split_to_table",
}


def _pattern_literal(node: exp.Literal) -> bool:
    p = node.parent
    while p is not None and not isinstance(p, exp.Select):
        if isinstance(p, exp.Like | exp.ILike | exp.RegexpLike | exp.RegexpILike | exp.SimilarTo):
            return True
        if isinstance(p, exp.RegexpExtract | exp.RegexpReplace | exp.RegexpSplit | exp.Substring):
            return True
        if isinstance(p, exp.Anonymous) and str(p.name).lower() in _PATTERN_FUNCS:
            return True
        p = p.parent
    return False


def sql_shape(sql: str) -> dict[str, Any] | None:
    """What a statement reads and does, as sets a diff can compare. None when it does not parse."""
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except Exception:  # noqa: BLE001 - an unparsable statement has no shape
        return None
    if tree is None:
        return None
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    tables = sorted({t.name.lower() for t in tree.find_all(exp.Table)} - ctes - {""})
    joins = set()
    for j in tree.find_all(exp.Join):
        on = j.args.get("on")
        if on is None:
            continue
        for eq in on.find_all(exp.EQ):
            cols = sorted(c.name.lower() for c in eq.find_all(exp.Column))
            if cols:
                joins.add(" = ".join(cols))
        for like in on.find_all(exp.Like, exp.ILike):
            joins.add("~ " + " ".join(sorted(c.name.lower() for c in like.find_all(exp.Column))))
    patterns: set[str] = set()
    filters: set[str] = set()
    for lit in tree.find_all(exp.Literal):
        if not lit.is_string and not _is_in(lit, (exp.Where, exp.Having)):
            continue
        if _pattern_literal(lit):
            patterns.add(lit.this)
        elif _is_in(lit, (exp.Where, exp.Having)):
            filters.add(lit.this.lower())
    aggs = sorted({type(a).__name__.lower() for a in tree.find_all(exp.AggFunc)})
    group = [g.sql(dialect="postgres").lower() for g in tree.find_all(exp.Group)]
    order = tree.args.get("order")
    limit = tree.args.get("limit")
    return {
        "tables": tables,
        "joins": sorted(joins),
        "patterns": sorted(patterns),
        "filters": sorted(filters),
        "aggregates": aggs,
        "grouped": bool(group),
        "order": order.sql(dialect="postgres").lower() if order is not None else "",
        "limit": limit.sql(dialect="postgres").lower() if limit is not None else "",
    }


# aspect → the category its difference names, in the order they are tested
_ASPECTS = (
    ("tables", "wrong tables"),
    ("joins", "join differs"),
    ("patterns", "parse differs"),
    ("filters", "filter differs"),
    ("aggregates", "aggregation"),
    ("grouped", "aggregation"),
    ("order", "order / tie"),
    ("limit", "order / tie"),
)


def structure_diff(golden_sql: str, agent_sql: str) -> tuple[str, dict[str, Any]]:
    """The first structural category that tells the two statements apart, and every
    differing aspect (golden vs agent)."""
    g, a = sql_shape(golden_sql), sql_shape(agent_sql)
    if g is None or a is None:
        return "result differs", {"unparsed": "golden" if g is None else "agent"}
    diff = {k: {"golden": g[k], "agent": a[k]} for k, _ in _ASPECTS if g[k] != a[k]}
    for k, cat in _ASPECTS:
        if k in diff:
            return cat, diff
    return "result differs", diff


# ── scoring a run ───────────────────────────────────────────────────────────


@dataclass
class _Golden:
    id: int
    kind: str
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    error: str | None


def _load_goldens(query_ids: set[str]) -> dict[str, _Golden]:
    from dab_bench.eval import golden

    out = {}
    for qid, g in golden.current().items():
        if qid not in query_ids:
            continue
        ex = golden.execute(g["sql"])
        out[qid] = _Golden(int(g["id"]), g["kind"], g["sql"], ex.columns, ex.rows, ex.error)
    return out


def _agent_result(trace: dict[str, Any], sql: str) -> tuple[list[str], list[list[Any]], str | None]:
    """The rows the harness kept at submit time, or a fresh re-run when they were cut."""
    from dab_bench.eval import golden

    sub = trace.get("submission") or {}
    rows = sub.get("rows")
    if rows is not None and not sub.get("truncated") and len(rows) == sub.get("row_count"):
        return list(sub.get("columns") or []), rows, None
    ex = golden.execute(sql)
    return ex.columns, ex.rows, ex.error


def score_trial(
    row: dict[str, Any], trace: dict[str, Any], g: _Golden | None, submits: bool
) -> dict[str, Any]:
    from dab_bench.eval import golden

    out: dict[str, Any] = {
        "query_id": row["query_id"],
        "trial": row["trial"],
        "answer": row.get("passed"),
        "sql": None,
        "decision": None,
        "mode": row.get("mode"),
        "step": row.get("step"),
        "golden_id": g.id if g else None,
        "golden_kind": g.kind if g else None,
        "category": "",
        "detail": "",
        "structure": {},
        "result_diff": [],
    }

    def done(category: str, detail: str) -> dict[str, Any]:
        out["category"], out["detail"] = category, detail
        return out

    if g is None:
        return done("no golden", "scored on the answer only; outside the optimisation loop")
    if g.error:
        return done("no golden", f"the golden failed to re-run: {g.error}")
    sql = row.get("agent_sql")
    if not sql:
        why = (
            "this version has no submit_answer"
            if not submits
            else (row.get("error") or row.get("terminal_reason") or "no submit_answer call")
        )
        out["sql"] = False if submits else None
        return done("no SQL", str(why)[:200])
    a_cols, a_rows, err = _agent_result(trace, sql)
    if err:
        out["sql"] = False
        return done("SQL error", err[:200])
    cmp = compare_results(g.columns, g.rows, a_cols, a_rows, g.kind)
    out["sql"] = cmp["pass"]
    want = MODE_FOR_KIND[g.kind]
    out["decision"] = row.get("mode") == want
    answer = row.get("passed")  # an evidence question's validator still scores its answer
    if cmp["pass"]:
        if not out["decision"]:
            return done("decision", f"{row.get('mode')} where {want} was wanted")
        if answer:
            return done("solved", cmp["detail"])
        if want == "derived":
            return done("derived step wrong", f"right evidence; step: {row.get('step') or '—'}")
        return done("format", "right result; the validator rejects its shape")
    out["result_diff"] = golden.gold_diff(a_cols, a_rows, golden.render(g.columns, g.rows))[
        :DIFF_LINES
    ]
    if answer:
        return done("right answer another way", cmp["detail"])
    category, structure = structure_diff(g.sql, sql)
    out["structure"] = structure
    return done(category, cmp["detail"])


def _rate(xs: list[bool | None]) -> dict[str, int]:
    scored = [x for x in xs if x is not None]
    return {"passed": sum(1 for x in scored if x), "n": len(scored)}


def summarise(
    rows: list[dict[str, Any]], split: dict[str, list[str]] | None, submits: bool = True
) -> dict[str, Any]:
    def totals(rs: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "answer": _rate([r["answer"] for r in rs]),
            "sql": _rate([r["sql"] for r in rs]),
            "decision": _rate([r["decision"] for r in rs]),
        }

    first: dict[str, list[str]] = {}
    for r in rows:
        if submits and r["category"] not in NOT_OPTIMISED:
            first.setdefault(r["category"], []).append(r["query_id"])
    out: dict[str, Any] = {
        "totals": totals(rows),
        "goldens": sum(1 for r in rows if r["golden_id"] is not None),
        "optimise_first": [
            {"category": c, "n": len(q), "queries": q}
            for c, q in sorted(first.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        ],
        "categories": dict(Counter(r["category"] for r in rows)),
    }
    if split:
        where = {q: name for name, qs in split.items() for q in qs}
        for r in rows:
            r["split"] = where.get(r["query_id"])
        out["by_split"] = {
            name: totals([r for r in rows if r.get("split") == name]) for name in split
        }
    return out


def score_run(run_id: str, runs_dir: Path = RUNS_DIR) -> dict[str, Any]:
    """Score every trial of a run three ways; write and return `scorecard.json`."""
    from dab_bench.agent.versions import load_version

    run_dir = runs_dir / run_id
    meta = json.loads((run_dir / "run.json").read_text())
    results = [
        json.loads(line)
        for line in (run_dir / "results.jsonl").read_text().splitlines()
        if line.strip()
    ]
    try:
        submits = load_version(meta["agent"]).submits_sql
    except FileNotFoundError:
        submits = any(r.get("mode") for r in results)
    goldens = _load_goldens({r["query_id"] for r in results})
    rows = []
    for r in results:
        tp = run_dir / (r.get("trace_file") or "")
        trace = json.loads(tp.read_text()) if r.get("trace_file") and tp.exists() else {}
        rows.append(score_trial(r, trace, goldens.get(r["query_id"]), submits))
    split = load_optimise_split()
    card = {"run_id": run_id, "agent": meta["agent"], "submits_sql": submits} | summarise(
        rows, split, submits
    )
    card["questions"] = rows
    (run_dir / "scorecard.json").write_text(json.dumps(card, ensure_ascii=False, indent=1) + "\n")
    return card


def load_scorecard(run_id: str, runs_dir: Path = RUNS_DIR) -> dict[str, Any] | None:
    p = runs_dir / run_id / "scorecard.json"
    return json.loads(p.read_text()) if p.exists() else None
