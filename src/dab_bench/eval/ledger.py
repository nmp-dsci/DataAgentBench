"""The SQL ledger (plan s08, D33): where an agent's statement goes a different way from the golden.

A statement is a plan with seven steps, in the order it is built (`COMPONENTS`): sources,
keys, parse, filter, metric, rank, shape. The **reader** (`agents/reader/`, Sonnet 5 at
medium) writes one line of words per step:

- for every golden, once, cached by golden id in `dataagentbench_meta.golden_ledger`, so a
  new save of the golden gets new lines;
- for every trial whose SQL fails, beside the golden's lines: the agent's seven lines, a
  verdict per step (`same` · `differs` · `none`), the first step whose difference changes
  the result (`breaks_at`) and one sentence on why. These go to `runs/<id>/ledger.json`.

`dab diagnose --ledger` runs it; `score_run` then reads `ledger.json` into the scorecard, and a
failed trial's category becomes the step it breaks at. The reader sees goldens, so its lines
are stored only beside the golden and the run, never in a prompt; a gold value it writes
literally is redacted before it is stored (the guard's own check). The optimiser reads the
lines; what it writes from them passes the guard as before.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dab_bench.config import AGENTS_DIR, PG_META_SCHEMA, RUNS_DIR

COMPONENTS = ("sources", "keys", "parse", "filter", "metric", "rank", "shape")
VERDICTS = ("same", "differs", "none")
WHAT = {
    "sources": "which tables, and which field inside them, hold what the question names",
    "keys": "how rows from different tables match, and what each side needs first",
    "parse": "what is read out of free text or JSON, and how",
    "filter": "which rows count: every condition, the window, exclusions",
    "metric": "what is measured, at what grain, by what formula",
    "rank": "the order, the tie-break, the limit",
    "shape": "what comes out: the columns, one row or many, rounding, format",
}
READER_DIR = AGENTS_DIR / "reader"
LEDGER_TABLE = "golden_ledger"
WORKERS = 6
DIFF_LINES = 30

DDL = f"""
create table if not exists {PG_META_SCHEMA}.{LEDGER_TABLE} (
  golden_id   bigint primary key,           -- golden_sql.id: a new save gets new lines
  query_id    text not null,
  lines       jsonb not null,               -- {{component: one line of words}}
  model       text not null,
  cost_usd    double precision,
  created_at  timestamptz not null default now()
);
comment on table {PG_META_SCHEMA}.{LEDGER_TABLE} is
  'The reader''s seven lines per golden (plan s08). Describes a golden, so never granted to dab_agent.';
"""


def ensure_table() -> None:
    from dab_bench.data import pg

    with pg.connect() as con:
        con.execute(DDL)  # type: ignore[arg-type,unused-ignore]
        con.execute(f"revoke all on {PG_META_SCHEMA}.{LEDGER_TABLE} from dab_agent")  # type: ignore[arg-type,unused-ignore]


def cached(golden_ids: list[int], model: str | None = None) -> dict[int, dict[str, str]]:
    """The stored lines of these goldens (only those `model` wrote, when given)."""
    if not golden_ids:
        return {}
    from dab_bench.data import pg

    ensure_table()
    with pg.connect() as con:
        rows = con.execute(
            f"select golden_id, lines, model from {PG_META_SCHEMA}.{LEDGER_TABLE} where golden_id = any(%s)",  # type: ignore[arg-type,unused-ignore]
            (golden_ids,),
        ).fetchall()
    return {int(r[0]): dict(r[1]) for r in rows if model is None or r[2] == model}


def store(
    golden_id: int, query_id: str, lines: dict[str, str], model: str, cost: float | None
) -> None:
    from dab_bench.data import pg

    ensure_table()
    with pg.connect() as con:
        con.execute(
            f"""insert into {PG_META_SCHEMA}.{LEDGER_TABLE} (golden_id, query_id, lines, model, cost_usd)
                values (%s, %s, %s, %s, %s)
                on conflict (golden_id) do update set lines = excluded.lines, model = excluded.model,
                  cost_usd = excluded.cost_usd, created_at = now()""",  # type: ignore[arg-type,unused-ignore]
            (golden_id, query_id, json.dumps(lines), model, cost),
        )


# ── what the reader writes, checked ──────────────────────────────────────────


def clean_lines(raw: Any) -> dict[str, str]:
    """Seven lines, one per component, trimmed to 400 characters; a missing one reads 'none'."""
    raw = raw if isinstance(raw, dict) else {}
    return {c: (str(raw.get(c) or "none").strip() or "none")[:400] for c in COMPONENTS}


def clean_verdicts(raw: Any) -> dict[str, str]:
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for c in COMPONENTS:
        v = str(raw.get(c) or "").strip().lower()
        out[c] = v if v in VERDICTS else "same"
    return out


def first_break(verdicts: dict[str, str], named: str | None) -> str | None:
    """The reader's `breaks_at` when it is a component that differs; else the first that does."""
    if named in COMPONENTS and verdicts.get(named) == "differs":
        return named
    return next((c for c in COMPONENTS if verdicts.get(c) == "differs"), None)


def redact(lines: dict[str, str], golds: list[tuple[str, str]]) -> tuple[dict[str, str], list[str]]:
    """Replace any gold value written literally (the guard's rule) with '…'."""
    import re

    from dab_bench.eval.guards import gold_literals

    hits: set[str] = set()
    out = {}
    for c, text in lines.items():
        found = gold_literals(text, golds)
        for v in found:
            text = re.sub(r"(?<![a-z0-9])" + re.escape(v) + r"(?![a-z0-9])", "…", text, flags=re.I)
        hits |= set(found)
        out[c] = text
    return out, sorted(hits)


def sql_sha(sql: str) -> str:
    return hashlib.sha256(" ".join(sql.split()).encode()).hexdigest()[:12]


# ── one reader call ──────────────────────────────────────────────────────────

_LINES_SCHEMA = {
    "type": "object",
    "properties": {c: {"type": "string", "description": WHAT[c]} for c in COMPONENTS},
    "required": list(COMPONENTS),
}
GOLDEN_SCHEMA = {
    "type": "object",
    "properties": {"lines": _LINES_SCHEMA},
    "required": ["lines"],
}
COMPARE_SCHEMA = {
    "type": "object",
    "properties": {
        "agent": _LINES_SCHEMA,
        "verdicts": {
            "type": "object",
            "properties": {c: {"type": "string", "enum": list(VERDICTS)} for c in COMPONENTS},
            "required": list(COMPONENTS),
        },
        "breaks_at": {"type": "string", "enum": [*COMPONENTS, "none"]},
        "why": {"type": "string"},
    },
    "required": ["agent", "verdicts", "breaks_at", "why"],
}


@dataclass
class Call:
    out: dict[str, Any] | None = None
    cost_usd: float | None = None
    n_turns: int = 0
    error: str | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)


async def ask(
    system_prompt: str,
    message: str,
    schema: dict[str, Any],
    model: str | None = None,
    agent: str = "reader",
    tool_name: str = "write_ledger",
) -> Call:
    """One isolated session: the prompt, the message, one tool that records its input.
    `model` overrides the agent's agent.yaml for this call; `agent` and `tool_name` let the
    reviewer (s11 G1, `eval/review.py`) use the same isolation."""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        SystemMessage,
        create_sdk_mcp_server,
        tool,
    )

    from dab_bench.agent.isolation import (
        SESSION_SETTINGS,
        IsolationError,
        check_init,
        isolated_cwd,
    )
    from dab_bench.agent.llm import EFFORT, require_live, resolve_model, subscription_env
    from dab_bench.agent.session import _block_to_dict
    from dab_bench.agent.versions import load_version

    require_live()
    cfg = load_version(agent).config
    call = Call()

    @tool(tool_name, "Record the result. Call once, then stop.", schema)
    async def write_ledger(args: dict[str, Any]) -> dict[str, Any]:
        call.out = dict(args)
        return {"content": [{"type": "text", "text": "Recorded. Stop now."}]}

    allowed = [f"mcp__dab__{tool_name}"]
    cwd = isolated_cwd()
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=resolve_model(model or cfg.model),
        tools=[],
        allowed_tools=allowed,
        mcp_servers={
            "dab": create_sdk_mcp_server(name="dab", version="1.0.0", tools=[write_ledger])
        },
        strict_mcp_config=True,
        permission_mode="bypassPermissions",
        max_turns=cfg.max_turns,
        cwd=str(cwd),
        env=subscription_env(),
        setting_sources=[],
        settings=SESSION_SETTINGS,
        effort=cfg.effort or EFFORT,  # type: ignore[arg-type]
    )
    t0 = time.time()

    async def _run() -> None:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(message)
            async for msg in client.receive_response():
                if isinstance(msg, SystemMessage) and msg.subtype == "init":
                    problems = check_init(msg.data, allowed, cwd)
                    if problems:
                        raise IsolationError("; ".join(problems))
                elif isinstance(msg, AssistantMessage):
                    call.trace.append(
                        {
                            "t": round(time.time() - t0, 3),
                            "content": [_block_to_dict(b) for b in msg.content],
                        }
                    )
                elif isinstance(msg, ResultMessage):
                    call.n_turns = msg.num_turns
                    call.cost_usd = msg.total_cost_usd
                    if msg.is_error and call.out is None:
                        call.error = f"{msg.subtype}: {(msg.errors or [msg.result or ''])[0]}"[:300]

    try:
        await asyncio.wait_for(_run(), timeout=cfg.timeout_s)
    except IsolationError:
        raise
    except TimeoutError:
        call.error = f"timeout after {cfg.timeout_s}s"
    except Exception as e:  # noqa: BLE001 - recorded; the other statements carry on
        call.error = f"{type(e).__name__}: {e}"[:300]
    if call.out is None and not call.error:
        call.error = f"the {agent} did not call {tool_name}"
    return call


def golden_message(question: str, sql: str) -> str:
    return f"## Question\n\n{question}\n\n## Statement\n\n```sql\n{sql.strip()}\n```\n"


def compare_message(
    question: str,
    golden_lines: dict[str, str],
    golden_sql: str,
    agent_sql: str,
    detail: str,
    diff: list[dict[str, Any]],
) -> str:
    lines = "\n".join(f"- {c}: {golden_lines.get(c, 'none')}" for c in COMPONENTS)
    d = "\n".join(
        ("  " if x["op"] == "eq" else "- " if x["op"] == "del" else "+ ") + x["text"]
        for x in diff[:DIFF_LINES]
    )
    return "\n\n".join(
        [
            f"## Question\n\n{question}",
            f"## The reference's seven lines\n\n{lines}",
            f"## Reference statement\n\n```sql\n{golden_sql.strip()}\n```",
            f"## Agent statement\n\n```sql\n{agent_sql.strip()}\n```",
            f"## How the results differ\n\n{detail}"
            + (f"\n\n```\n{d}\n```\n(- reference rows, + agent rows)" if d else ""),
        ]
    )


# ── a run's ledger ───────────────────────────────────────────────────────────


def ledger_path(run_id: str, runs_dir: Path = RUNS_DIR) -> Path:
    return runs_dir / run_id / "ledger.json"


def load_ledger(run_id: str, runs_dir: Path = RUNS_DIR) -> dict[str, Any] | None:
    p = ledger_path(run_id, runs_dir)
    return json.loads(p.read_text()) if p.exists() else None


def needs_comparison(q: dict[str, Any], agent_sql: str | None) -> bool:
    """A trial whose statement ran and whose result is not the golden's."""
    return bool(
        agent_sql
        and q.get("golden_id") is not None
        and q.get("sql") is False
        and q.get("category") not in ("no SQL", "SQL error", "no golden")
    )


async def build(
    run_id: str, refresh: bool = False, workers: int = WORKERS, model: str | None = None
) -> dict[str, Any]:
    """Write `runs/<id>/ledger.json`: every golden's lines (cached) and, for every trial whose
    SQL fails, the comparison. `refresh` re-reads what is already there. `model` overrides the
    reader's agent.yaml; a golden's cached lines and a run's earlier comparisons are reused only
    when the same model wrote them."""
    from dab_bench.agent.llm import resolve_model
    from dab_bench.agent.versions import load_version
    from dab_bench.data.index import load
    from dab_bench.eval import golden
    from dab_bench.eval.scorecard import load_scorecard, score_run

    run_dir = RUNS_DIR / run_id
    card = load_scorecard(run_id) or score_run(run_id)
    results = {
        r["query_id"]: r
        for r in (
            json.loads(line)
            for line in (run_dir / "results.jsonl").read_text().splitlines()
            if line.strip()
        )
        if r["trial"] == 1
    }
    ix = load()
    by_id = {q["id"]: q for q in ix.queries}
    golds = [(q["question"], q.get("gold_text") or "") for q in ix.queries]
    goldens = golden.current()
    reader = load_version(READER_DIR.name)
    model = resolve_model(model or reader.config.model)
    compare_prompt = (READER_DIR / "compare.md").read_text()
    old = (None if refresh else load_ledger(run_id)) or {}
    if old.get("model") != model:
        old = {}  # another reader wrote it: read it again
    sem = asyncio.Semaphore(max(1, workers))
    cost = 0.0
    errors: list[str] = []

    # 1 · the goldens' lines, cached by golden id
    qids = sorted(
        q["query_id"] for q in card["questions"] if q["golden_id"] is not None and q["trial"] == 1
    )
    want = {qid: int(goldens[qid]["id"]) for qid in qids if qid in goldens}
    have = {} if refresh else cached(list(want.values()), model)

    async def read_golden(qid: str, gid: int) -> tuple[str, dict[str, str] | None]:
        nonlocal cost
        async with sem:
            c = await ask(
                reader.system_prompt,
                golden_message(by_id[qid]["question"], goldens[qid]["sql"]),
                GOLDEN_SCHEMA,
                model,
            )
        cost += c.cost_usd or 0.0
        if c.error or c.out is None:
            errors.append(f"{qid} golden: {c.error}")
            return qid, None
        lines, _ = redact(clean_lines(c.out.get("lines")), golds)
        store(gid, qid, lines, model, c.cost_usd)
        return qid, lines

    todo = [(q, g) for q, g in want.items() if g not in have]
    got = dict(await asyncio.gather(*(read_golden(q, g) for q, g in todo)))
    golden_lines = {q: have[g] for q, g in want.items() if g in have} | {
        q: v for q, v in got.items() if v is not None
    }

    # 2 · the comparisons, for every trial whose SQL fails
    rows = {q["query_id"]: q for q in card["questions"] if q["trial"] == 1}
    prev = old.get("questions") or {}

    async def compare(qid: str) -> tuple[str, dict[str, Any] | None]:
        nonlocal cost
        q, r = rows[qid], results[qid]
        sha = sql_sha(r["agent_sql"])
        p = prev.get(qid)
        if p and p.get("golden_id") == want[qid] and p.get("agent_sql_sha") == sha:
            return qid, p
        msg = compare_message(
            by_id[qid]["question"],
            golden_lines[qid],
            goldens[qid]["sql"],
            r["agent_sql"],
            q.get("sql_detail") or q.get("detail") or "",
            q.get("result_diff") or [],
        )
        async with sem:
            c = await ask(compare_prompt, msg, COMPARE_SCHEMA, model)
        cost += c.cost_usd or 0.0
        if c.error or c.out is None:
            errors.append(f"{qid} compare: {c.error}")
            return qid, None
        agent, _ = redact(clean_lines(c.out.get("agent")), golds)
        verdicts = clean_verdicts(c.out.get("verdicts"))
        why, _ = redact({"why": str(c.out.get("why") or "")[:400]}, golds)
        return qid, {
            "golden_id": want[qid],
            "agent_sql_sha": sha,
            "agent": agent,
            "verdicts": verdicts,
            "breaks_at": first_break(verdicts, str(c.out.get("breaks_at") or "")),
            "why": why["why"],
            "cost_usd": c.cost_usd,
        }

    cmp_ids = [
        qid
        for qid, q in rows.items()
        if qid in golden_lines and needs_comparison(q, results.get(qid, {}).get("agent_sql"))
    ]
    compared = {k: v for k, v in await asyncio.gather(*(compare(q) for q in cmp_ids)) if v}
    ledger = {
        "run_id": run_id,
        "model": model,
        "created_at": datetime.now(UTC).isoformat(),
        "cost_usd": round(cost + float(old.get("cost_usd") or 0.0) if not refresh else cost, 4),
        "components": list(COMPONENTS),
        "goldens": {
            q: {"golden_id": want[q], "lines": golden_lines[q]} for q in sorted(golden_lines)
        },
        "questions": compared,
        "errors": errors,
    }
    ledger_path(run_id).write_text(json.dumps(ledger, ensure_ascii=False, indent=1) + "\n")
    return ledger


def attach(
    rows: list[dict[str, Any]], ledger: dict[str, Any] | None, agent_sql: dict[str, str]
) -> None:
    """Read a run's ledger into its scorecard rows: the golden's lines where the golden is the
    one the ledger read, and a comparison where the agent's statement is the one it compared.
    A failed trial with a break is categorised by the step it breaks at."""
    if not ledger:
        return
    gl = ledger.get("goldens") or {}
    qs = ledger.get("questions") or {}
    for row in rows:
        if row.get("trial") != 1:
            continue
        qid = row["query_id"]
        g = gl.get(qid)
        if not g or g.get("golden_id") != row.get("golden_id"):
            continue
        entry: dict[str, Any] = {"golden": g["lines"]}
        c = qs.get(qid)
        sql = agent_sql.get(qid)
        if (
            c
            and sql
            and c.get("golden_id") == row.get("golden_id")
            and c.get("agent_sql_sha") == sql_sha(sql)
        ):
            entry |= {
                "agent": c["agent"],
                "verdicts": c["verdicts"],
                "breaks_at": c.get("breaks_at"),
                "why": c.get("why") or "",
            }
            if row.get("sql") is False and row.get("category") not in ("no SQL", "SQL error"):
                row["category"] = (
                    f"breaks at {c['breaks_at']}" if c.get("breaks_at") else "result differs"
                )
                row["breaks_at"] = c.get("breaks_at")
        row["ledger"] = entry
