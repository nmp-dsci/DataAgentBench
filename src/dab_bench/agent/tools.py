"""The agent's tool belt: one in-process MCP server (`dab`) bound to one trial.

Orient: `list_db`, `describe_table`, `sample_rows`, `read_context`, `search_context` —
files from the pack and the live schema, no bytes moved.
Compute: `query_db(sql, save_as=)` as the read-only role (rows back, or parquet on the
trial's `/work` for Python); `execute_python(code)` in the network-off sandbox;
`llm_extract(sql, column, instruction, labels)` for text columns.
Answer: `return_answer(answer)` records the value; the harness takes it as final.
Or, for a version that answers with SQL (s06, D27): `submit_answer(sql, mode, answer?, step?)`.
The harness re-runs `sql` as the read-only role and keeps its columns, rows and rendered
text, so the agent's result is known exactly, not as the model retold it. Mode
`pass_through`: the answer is that rendered result. Mode `derived`: the model writes the
answer from the rows and says in one line what it did (`step`).

Every tool result is cut at 10 000 characters (the reference scaffold's rule).
The state object is the trace the run keeps: every call, its inputs, its result.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
from claude_agent_sdk import create_sdk_mcp_server, tool
from claude_agent_sdk.types import McpSdkServerConfig

from dab_bench.agent.prompt import DatasetContext
from dab_bench.agent.sandbox import Sandbox, cut
from dab_bench.config import PG_SCHEMA, settings

RESULT_CUT = 10_000
DEFAULT_LIMIT = 50
MAX_LIMIT = 500
SAVE_MAX_ROWS = 2_000_000
EXTRACT_MAX_ROWS = 2_000
EXTRACT_BATCH = 40


@dataclass
class ToolState:
    dataset: str
    ctx: DatasetContext
    trial_key: str  # `<dataset>_<n>_t<k>` — the /work subdirectory
    sandbox: Sandbox | None
    exec_timeout_s: int = 600
    answer: str | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)
    extract_cost_usd: float = 0.0
    extract_input_tokens: int = 0
    extract_output_tokens: int = 0
    submission: dict[str, Any] | None = None  # submit_answer's record: sql, result, mode, step

    def record(
        self, name: str, inputs: dict[str, Any], output: str, t0: float, error: bool = False
    ) -> None:
        self.calls.append(
            {
                "tool": name,
                "input": inputs,
                "output": output[:RESULT_CUT],
                "chars": len(output),
                "elapsed_s": round(time.time() - t0, 3),
                "error": error,
            }
        )

    @property
    def work_dir(self) -> Path | None:
        return self.sandbox.trial_dir(self.trial_key) if self.sandbox else None


def _connect() -> psycopg.Connection[Any]:
    return psycopg.connect(settings().agent_database_url, autocommit=True)


def _render_rows(cols: list[str], rows: list[tuple[Any, ...]], total: int | None = None) -> str:
    if not rows:
        return "(0 rows)"
    lines = ["\t".join(cols)]
    for r in rows:
        lines.append("\t".join("NULL" if v is None else _cell(v) for v in r))
    foot = (
        f"({len(rows)} rows shown"
        + (f" of {total}" if total is not None and total > len(rows) else "")
        + ")"
    )
    return "\n".join(lines) + "\n" + foot


def _cell(v: Any) -> str:
    s = json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, dict | list) else str(v)
    s = s.replace("\n", "\\n").replace("\t", " ")
    return s if len(s) <= 300 else s[:300] + "…"


_FORBIDDEN = re.compile(r"^\s*(insert|update|delete|drop|alter|create|truncate|grant|copy)\b", re.I)


def run_sql(state: ToolState, sql: str, limit: int, save_as: str | None) -> str:
    sql = sql.strip().rstrip(";")
    if _FORBIDDEN.match(sql):
        return "Error: only read-only SQL is allowed (the role cannot write anyway)."
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    with _connect() as con:
        if save_as:
            name = re.sub(r"[^A-Za-z0-9_.-]", "_", save_as)
            if not name.endswith(".parquet"):
                name += ".parquet"
            work = state.work_dir
            if work is None:
                return (
                    "Error: no sandbox for this run, so save_as has nowhere to write; drop save_as."
                )
            import pyarrow as pa
            import pyarrow.parquet as pq

            with (
                con.transaction(),
                con.cursor(name="dab_save") as scur,
            ):  # server-side cursor: streams
                scur.itersize = 50_000
                scur.execute(sql)  # type: ignore[arg-type,unused-ignore]
                cols = [d.name for d in scur.description or []]
                n = 0
                head: list[tuple[Any, ...]] = []
                writer: pq.ParquetWriter | None = None
                for rows in iter(lambda: scur.fetchmany(50_000), []):
                    if not head:
                        head = rows[:5]
                    table = pa.Table.from_pylist(
                        [dict(zip(cols, (_arrow_safe(v) for v in r), strict=True)) for r in rows]
                    )
                    if writer is None:
                        writer = pq.ParquetWriter(work / name, table.schema)
                    writer.write_table(table)
                    n += len(rows)
                    if n >= SAVE_MAX_ROWS:
                        break
                if writer is None:
                    pa_table = pa.Table.from_pylist([{c: None for c in cols}]).slice(0, 0)
                    pq.write_table(pa_table, work / name)
                else:
                    writer.close()
            return (
                f"saved {n:,} rows × {len(cols)} columns to /work/{state.trial_key}/{name} "
                f"(read it in execute_python with pd.read_parquet('{name}')).\n"
                + _render_rows(cols, head)
            )
        cur = con.execute(f"SELECT * FROM ({sql}) AS _q LIMIT {limit + 1}")  # type: ignore[arg-type,unused-ignore]
        cols = [d.name for d in cur.description or []]
        rows = cur.fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        text = _render_rows(cols, rows)
        if more:
            text += f"\n(more rows exist: raise limit (max {MAX_LIMIT}) or aggregate; save_as= writes them all to parquet)"
        return text


def _arrow_safe(v: Any) -> Any:
    if isinstance(v, dict | list):
        return json.dumps(v, ensure_ascii=False, default=str)
    return v


def _describe(state: ToolState, table: str) -> str:
    entry = next((t for t in state.ctx.tables if t.get("table") == table), None)
    prof: dict[str, Any] = {}
    p = state.ctx.path / "profile.json"
    if p.exists():
        prof = json.loads(p.read_text()).get(table, {})
    if entry is None and not prof:
        with _connect() as con:
            rows = con.execute(
                "select column_name, data_type from information_schema.columns "
                "where table_schema = %s and table_name = %s order by ordinal_position",
                (PG_SCHEMA, table),
            ).fetchall()
        if not rows:
            return f"no table {table!r}; list_db shows the names"
        return "\n".join(f"{c}\t{t}" for c, t in rows)
    lines = []
    if entry:
        lines.append(
            f"{table}: {int(entry.get('rows') or 0):,} rows · store {entry.get('store')} · source table {entry.get('source_table')}"
        )
        if entry.get("family"):
            fam = entry["family"]
            lines.append(
                f"one of {len(fam['members']):,} tables with identical columns; query them together via {fam.get('union_table')} (column _table = member name)"
            )
        if entry.get("primary_key"):
            lines.append(f"primary key: {', '.join(entry['primary_key'])}")
    lines.append("column\ttype\tnull_rate\tdistinct\tmin\tmax\ttop values")
    cols = (
        entry["columns"] if entry else [{"name": c, "type": e.get("type")} for c, e in prof.items()]
    )
    for c in cols:
        e = prof.get(c["name"], {})
        top = "; ".join(f"{v} ({n})" for v, n in (e.get("top") or [])[:6])
        if e.get("json_keys"):
            keys = e["json_keys"]
            top = "keys: " + ", ".join(list(keys)[:12])
        lines.append(
            f"{c['name']}\t{c.get('type')}\t{e.get('null_rate', '')}\t{e.get('distinct', '')}\t{e.get('min', '')}\t{e.get('max', '')}\t{top}"
        )
    return "\n".join(lines)


def _read_context(state: ToolState, path: str) -> str:
    base = state.ctx.path.resolve()
    target = (base / path).resolve()
    if base not in target.parents and target != base:
        return "Error: path must be inside the dataset's context pack"
    if target.is_dir():
        return "\n".join(sorted(p.name for p in target.iterdir()))
    if not target.exists():
        listing = "\n".join(
            sorted(str(p.relative_to(base)) for p in base.rglob("*") if p.is_file())
        )
        return f"no file {path!r}. Files:\n{listing}"
    return target.read_text()


def _search_context(state: ToolState, term: str) -> str:
    base = state.ctx.path
    rx = re.compile(re.escape(term), re.I)
    hits = []
    for p in sorted(base.rglob("*")):
        if not p.is_file() or p.suffix not in {".md", ".txt", ".json"}:
            continue
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if rx.search(line):
                hits.append(f"{p.relative_to(base)}:{i}: {line.strip()[:200]}")
            if len(hits) >= 60:
                break
    return "\n".join(hits) if hits else f"no match for {term!r} in the pack"


async def _llm_extract(
    state: ToolState,
    sql: str,
    column: str,
    instruction: str,
    labels: list[str] | None,
    save_as: str,
) -> str:
    """Batch a text column through Haiku; write the rows plus a `label` column to parquet."""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        TextBlock,
    )

    from dab_bench.agent.llm import EFFORT, resolve_model, subscription_env
    from dab_bench.config import ROOT

    work = state.work_dir
    if work is None:
        return "Error: no sandbox for this run; llm_extract needs /work to write to."
    sql = sql.strip().rstrip(";")
    with _connect() as con:
        cur = con.execute(f"SELECT * FROM ({sql}) AS _q LIMIT {EXTRACT_MAX_ROWS + 1}")  # type: ignore[arg-type,unused-ignore]
        cols = [d.name for d in cur.description or []]
        rows = cur.fetchall()
    if column not in cols:
        return f"Error: column {column!r} is not in the query's columns {cols}"
    truncated = len(rows) > EXTRACT_MAX_ROWS
    rows = rows[:EXTRACT_MAX_ROWS]
    ci = cols.index(column)
    label_rule = (
        f"Answer with exactly one of these labels per item: {', '.join(labels)}."
        if labels
        else "Answer with a short value per item."
    )
    system = (
        "You label text items. Reply with one line per item in the form `<index>: <label>`, nothing else. "
        + label_rule
    )
    out_labels: list[str | None] = [None] * len(rows)
    options = ClaudeAgentOptions(
        system_prompt=system,
        model=resolve_model("haiku"),
        tools=[],
        allowed_tools=[],
        permission_mode="bypassPermissions",
        max_turns=1,
        cwd=str(ROOT),
        env=subscription_env(),
        setting_sources=[],
        effort=EFFORT,
    )
    for start in range(0, len(rows), EXTRACT_BATCH):
        batch = rows[start : start + EXTRACT_BATCH]
        items = "\n".join(
            f"[{start + i}] {str(r[ci])[:1500].replace(chr(10), ' ')}" for i, r in enumerate(batch)
        )
        prompt = f"Instruction: {instruction}\n\nItems:\n{items}"
        text = ""
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    t = [b.text for b in msg.content if isinstance(b, TextBlock)]
                    if t:
                        text = t[-1]
                elif isinstance(msg, ResultMessage):
                    state.extract_cost_usd += msg.total_cost_usd or 0.0
                    u = msg.usage or {}
                    state.extract_input_tokens += (
                        int(u.get("input_tokens", 0))
                        + int(u.get("cache_read_input_tokens", 0))
                        + int(u.get("cache_creation_input_tokens", 0))
                    )
                    state.extract_output_tokens += int(u.get("output_tokens", 0))
        for m in re.finditer(r"^\s*\[?(\d+)\]?\s*:\s*(.+?)\s*$", text, re.M):
            i = int(m.group(1))
            if 0 <= i < len(rows):
                out_labels[i] = m.group(2).strip()
    import pyarrow as pa
    import pyarrow.parquet as pq

    name = re.sub(r"[^A-Za-z0-9_.-]", "_", save_as)
    if not name.endswith(".parquet"):
        name += ".parquet"
    table = pa.Table.from_pylist(
        [
            {**dict(zip(cols, (_arrow_safe(v) for v in r), strict=True)), "label": out_labels[i]}
            for i, r in enumerate(rows)
        ]
    )
    pq.write_table(table, work / name)
    counts: dict[str, int] = {}
    for lab in out_labels:
        counts[lab or "(none)"] = counts.get(lab or "(none)", 0) + 1
    summary = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])[:20])
    return (
        f"labelled {len(rows):,} rows"
        + (f" (query returned more; capped at {EXTRACT_MAX_ROWS})" if truncated else "")
        + f" → /work/{state.trial_key}/{name} with columns {cols + ['label']}.\nlabel counts: {summary}"
    )


# ── the tool table: one spec per tool, one body per tool, one dispatcher ─────────
# `make_tool_server` (a trial) and the explorer's playground both go through `call_tool`,
# so a tool cannot behave differently in the two places.


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    schema: dict[str, Any]
    backend: str  # "pack" | "postgres" | "sandbox" | "model" | "state"
    calls_model: bool = False


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


TOOL_SPECS: dict[str, ToolSpec] = {
    t.name: t
    for t in (
        ToolSpec(
            "list_db",
            "The stores and tables of this dataset with row counts and columns (from the context pack).",
            _obj({}, []),
            "pack",
        ),
        ToolSpec(
            "describe_table",
            "Columns, types, null rate, distinct count, min/max and top values of one table.",
            _obj({"table": {"type": "string"}}, ["table"]),
            "postgres",
        ),
        ToolSpec(
            "sample_rows",
            "A few rows of one table (default 5, max 20).",
            _obj({"table": {"type": "string"}, "n": {"type": "integer"}}, ["table"]),
            "postgres",
        ),
        ToolSpec(
            "query_db",
            "Run read-only Postgres SQL against the dataset (schema dataagentbench is the search_path; tables are "
            "<dataset>_<table>). Returns up to `limit` rows (default 50, max 500). With `save_as`, writes ALL result rows "
            "to /work/<save_as>.parquet for execute_python and returns the first rows.",
            _obj(
                {
                    "sql": {"type": "string", "description": "read-only SELECT / WITH query"},
                    "limit": {
                        "type": "integer",
                        "description": "rows to return (default 50, max 500)",
                    },
                    "save_as": {
                        "type": "string",
                        "description": "optional: write all result rows to /work/<save_as>.parquet for execute_python",
                    },
                },
                ["sql"],
            ),
            "postgres",
        ),
        ToolSpec(
            "execute_python",
            "Run Python 3.12 in a sandbox with no network (pandas, numpy, pyarrow, duckdb, scipy). The working directory "
            "is this trial's /work folder, where query_db(save_as=…) parquet files are; each call is a fresh process, so "
            "print what you need and save intermediate results to files. Output is cut at 10 000 chars.",
            _obj({"code": {"type": "string"}}, ["code"]),
            "sandbox",
        ),
        ToolSpec(
            "llm_extract",
            "Label a text column with a small model. Runs `sql` (≤ 2000 rows), sends `column` in batches with your "
            "`instruction` (and optional fixed `labels`), and writes the rows plus a `label` column to /work/<save_as>.parquet. "
            "Use it for categories, entities or facts that live in free text, never for arithmetic.",
            _obj(
                {
                    "sql": {
                        "type": "string",
                        "description": "query selecting the rows (≤ 2000) incl. the text column",
                    },
                    "column": {"type": "string", "description": "the text column to label"},
                    "instruction": {
                        "type": "string",
                        "description": "what to extract or decide per item",
                    },
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "optional fixed label set; omit for free-form values",
                    },
                    "save_as": {
                        "type": "string",
                        "description": "parquet name under /work (default: extracted)",
                    },
                },
                ["sql", "column", "instruction"],
            ),
            "model",
            calls_model=True,
        ),
        ToolSpec(
            "read_context",
            "Read a file from the dataset's context pack (schema.md, joins.md, profile.json, samples/<table>.md, pitfalls.md); a directory lists its files.",
            _obj({"path": {"type": "string"}}, ["path"]),
            "pack",
        ),
        ToolSpec(
            "search_context",
            "Grep the context pack for a term (column names, values, words from the description).",
            _obj({"term": {"type": "string"}}, ["term"]),
            "pack",
        ),
        ToolSpec(
            "submit_answer",
            "Finish: submit the ONE final SQL statement and how the answer comes from it. The harness re-runs "
            "`sql` read-only. mode `pass_through`: the answer IS the SQL's result, rendered by the harness (one value "
            "alone, or a header line and one comma-separated line per row). mode `derived`: the answer needs one step "
            "after the SQL (reading returned text to reach a verdict, choosing between returned rows); give `answer` "
            "and describe the step in one line in `step`. A SQL error or an empty result is sent back to fix. Call it "
            "once it succeeds, then stop.",
            _obj(
                {
                    "sql": {
                        "type": "string",
                        "description": "the final read-only SELECT / WITH statement",
                    },
                    "mode": {"type": "string", "enum": ["pass_through", "derived"]},
                    "answer": {
                        "type": "string",
                        "description": "derived only: the answer, values only, no explanation",
                    },
                    "step": {
                        "type": "string",
                        "description": "derived only: one line on what was done after the SQL",
                    },
                },
                ["sql", "mode"],
            ),
            "state",
        ),
        ToolSpec(
            "return_answer",
            "Submit the final answer: the value(s) only, in the shape the question asks for, no explanation. Call it once, then stop.",
            _obj({"answer": {"type": "string"}}, ["answer"]),
            "state",
        ),
    )
}


def _list_db(state: ToolState, args: dict[str, Any]) -> tuple[dict[str, Any], str]:
    lines = []
    for t in state.ctx.tables:
        cols = ", ".join(str(c.get("name")) for c in t.get("columns") or [])
        fam = t.get("family")
        extra = (
            f" [family of {len(fam['members']):,} tables; union: {fam.get('union_table')}]"
            if fam
            else ""
        )
        lines.append(
            f"{t.get('table')} ({int(t.get('rows') or 0):,} rows; store {t.get('store')}){extra}: {cols}"
        )
    return {}, "\n".join(lines)


def _describe_table(state: ToolState, args: dict[str, Any]) -> tuple[dict[str, Any], str]:
    table = str(args.get("table", "")).strip().strip('"')
    return {"table": table}, _describe(state, table)


def _sample_rows(state: ToolState, args: dict[str, Any]) -> tuple[dict[str, Any], str]:
    table = str(args.get("table", "")).strip().strip('"')
    n = max(1, min(int(args.get("n") or 5), 20))
    return {"table": table, "n": n}, run_sql(state, f'SELECT * FROM {PG_SCHEMA}."{table}"', n, None)


def _query_db(state: ToolState, args: dict[str, Any]) -> tuple[dict[str, Any], str]:
    sql = str(args.get("sql", ""))
    limit = int(args.get("limit") or DEFAULT_LIMIT)
    save_as = str(args.get("save_as") or "").strip() or None if state.work_dir is not None else None
    inputs = {"sql": sql, "limit": limit, "save_as": save_as}
    try:
        return inputs, run_sql(state, sql, limit, save_as)
    except Exception as e:  # noqa: BLE001 - the model needs the first line of the error
        return inputs, f"Error: {type(e).__name__}: {str(e).splitlines()[0][:400]}"


def _execute_python(state: ToolState, args: dict[str, Any]) -> tuple[dict[str, Any], str]:
    code = str(args.get("code", ""))
    if state.sandbox is None:
        return {"code": code}, "Error: no sandbox in this run (dry run)"
    out, _ = state.sandbox.run(code, state.trial_key, state.exec_timeout_s)
    return {"code": code}, out


def _read_context_tool(state: ToolState, args: dict[str, Any]) -> tuple[dict[str, Any], str]:
    path = str(args.get("path", "")).strip() or "."
    return {"path": path}, _read_context(state, path)


def _search_context_tool(state: ToolState, args: dict[str, Any]) -> tuple[dict[str, Any], str]:
    term = str(args.get("term", ""))
    return {"term": term}, _search_context(state, term)


SUBMIT_PREVIEW_LINES = 20
MODES = ("pass_through", "derived")


def _submit_answer(state: ToolState, args: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Re-run the agent's SQL as dab_agent and record the result with the mode. A SQL error or
    an empty result is sent back (nothing recorded), so the agent can fix it and submit again."""
    from dab_bench.eval.golden import execute, render  # the golden's own executor and render

    sql = str(args.get("sql", "")).strip()
    mode = str(args.get("mode", "")).strip()
    answer = str(args.get("answer") or "").strip()
    step = str(args.get("step") or "").strip()
    inputs = {"sql": sql, "mode": mode, "answer": answer, "step": step}
    if mode not in MODES:
        return inputs, f"Error: mode must be one of {', '.join(MODES)}; nothing recorded."
    if mode == "derived" and not answer:
        return (
            inputs,
            "Error: mode derived needs `answer` (and a one-line `step`); nothing recorded.",
        )
    ex = execute(sql)
    if ex.error:
        return (
            inputs,
            f"Error: the SQL failed when re-run: {ex.error.removeprefix('Error: ')}. Fix it and submit again; nothing recorded.",
        )
    rendered = render(ex.columns, ex.rows)
    if not rendered:
        return inputs, "Error: the SQL returned no rows. Fix it and submit again; nothing recorded."
    state.submission = {
        "sql": sql,
        "mode": mode,
        "step": step,
        "model_answer": answer,
        "columns": ex.columns,
        "rows": ex.rows[:RESULT_ROWS_KEPT],
        "row_count": ex.row_count,
        "truncated": ex.truncated,
        "duration_ms": ex.duration_ms,
        "result": rendered,
    }
    state.answer = rendered if mode == "pass_through" else answer
    preview = "\n".join(rendered.splitlines()[:SUBMIT_PREVIEW_LINES])
    more = ex.row_count - (SUBMIT_PREVIEW_LINES - 1)
    tail = f"\n… {more} more row(s)" if len(rendered.splitlines()) > SUBMIT_PREVIEW_LINES else ""
    what = "the answer is this result" if mode == "pass_through" else f"the answer is {answer!r}"
    return (
        inputs,
        f"recorded ({mode}; {ex.row_count} row(s)); {what}:\n{preview}{tail}\nDo not call any more tools.",
    )


RESULT_ROWS_KEPT = 500  # the agent's result rows kept on the trace for the diagnosis


def _return_answer(state: ToolState, args: dict[str, Any]) -> tuple[dict[str, Any], str]:
    state.answer = str(args.get("answer", "")).strip()
    return {"answer": state.answer}, "recorded. Do not call any more tools."


_BODIES: dict[str, Any] = {
    "list_db": _list_db,
    "describe_table": _describe_table,
    "sample_rows": _sample_rows,
    "query_db": _query_db,
    "execute_python": _execute_python,
    "read_context": _read_context_tool,
    "search_context": _search_context_tool,
    "return_answer": _return_answer,
    "submit_answer": _submit_answer,
}


def call_tool(state: ToolState, name: str, args: dict[str, Any]) -> tuple[str, bool]:
    """Run one synchronous tool body against the state; returns (output cut at RESULT_CUT, is_error).
    Records the call on the state exactly as a trial does. `llm_extract` is async: see `call_tool_async`."""
    if name not in _BODIES:
        raise KeyError(name)
    t0 = time.time()
    inputs: dict[str, Any] = dict(args)
    try:
        inputs, out = _BODIES[name](state, args)
        err = out.startswith("Error")
    except Exception as e:  # noqa: BLE001 - the model needs the error text
        out, err = f"Error: {type(e).__name__}: {e}", True
    state.record(name, inputs, out, t0, err)
    return cut(out, RESULT_CUT), err


async def call_tool_async(state: ToolState, name: str, args: dict[str, Any]) -> tuple[str, bool]:
    """`call_tool` for every tool, with the blocking bodies off the event loop."""
    if name == "llm_extract":
        t0 = time.time()
        inputs = {k: args.get(k) for k in ("sql", "column", "instruction", "labels", "save_as")}
        try:
            out = await _llm_extract(
                state,
                str(args.get("sql", "")),
                str(args.get("column", "")),
                str(args.get("instruction", "")),
                [str(x) for x in (args.get("labels") or [])] or None,
                str(args.get("save_as") or "extracted"),
            )
            err = out.startswith("Error")
        except Exception as e:  # noqa: BLE001
            out, err = f"Error: {type(e).__name__}: {e}", True
        state.record("llm_extract", inputs, out, t0, err)
        return cut(out, RESULT_CUT), err
    return await asyncio.to_thread(call_tool, state, name, args)


def specs_for(tools: list[str] | None) -> list[ToolSpec]:
    """The specs a version's tool list names (`mcp__dab__<name>`), in the table's order.
    Without execute_python, `query_db` loses `save_as`: it only ever fed the sandbox."""
    names = None if tools is None else {t.removeprefix("mcp__dab__") for t in tools}
    out = []
    for spec in TOOL_SPECS.values():
        if names is not None and spec.name not in names:
            continue
        if spec.name == "query_db" and names is not None and "execute_python" not in names:
            props = {k: v for k, v in spec.schema["properties"].items() if k != "save_as"}
            spec = ToolSpec(
                spec.name,
                "Run read-only Postgres SQL against the dataset (schema dataagentbench is the search_path; tables "
                "are <dataset>_<table>). Returns up to `limit` rows (default 50, max 500).",
                _obj(props, ["sql"]),
                spec.backend,
            )
        out.append(spec)
    return out


def make_tool_server(state: ToolState, tools: list[str] | None = None) -> McpSdkServerConfig:
    """The `dab` MCP server for one trial: the version's own specs (`tools`, every spec when
    None), each wrapped around `call_tool_async`. A tool the version lacks is not registered,
    so the session cannot see it, let alone call it."""

    def _make(spec: ToolSpec) -> Any:
        async def _fn(args: dict[str, Any]) -> dict[str, Any]:
            out, err = await call_tool_async(state, spec.name, args)
            return {
                "content": [{"type": "text", "text": out}],
                **({"is_error": True} if err else {}),
            }

        _fn.__name__ = spec.name
        return tool(spec.name, spec.description, spec.schema)(_fn)

    return create_sdk_mcp_server(
        name="dab", version="1.0.0", tools=[_make(spec) for spec in specs_for(tools)]
    )
