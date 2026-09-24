"""Golden SQL: one curated Postgres query per question that reproduces its gold answer.

A golden is written by hand in the explorer's Golden tab. It runs exactly where the
agent's `query_db` runs, as `dab_agent`: read-only, `search_path = dataagentbench`,
60 s statement timeout. So a golden can only use what the agent can see. Its result
is rendered as text and judged by the question's own `validate.py`, the same judge a
trial gets. A golden that passes is proof the question is answerable in one SQL
statement over the loaded data.

A golden may start from an agent's own SQL (the Golden tab seeds the editor from a
run's trial), but a person reviews, runs and saves it; `source` records where it
started. Goldens are curated work, so they are never dropped: every save appends a row, and
the newest row per question is its current golden. They live in
`dataagentbench_meta`, next to the question copy, because a golden encodes the
answer: `dab_agent` is refused there (`infra/roles.sql`, `tests/test_golden.py`), and
no golden may reach a prompt, the pack or the curator.
"""

from __future__ import annotations

import getpass
import json
import re
import time
from concurrent.futures import ProcessPoolExecutor
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any

import psycopg

from dab_bench.config import PG_META_SCHEMA, SOURCE_PATH, settings
from dab_bench.data import pg

GOLDEN_TABLE = "golden_sql"
PROPOSAL_TABLE = "golden_proposal"
KINDS = ("answer", "evidence")
EVIDENCE_REASON = (
    "evidence golden: the question asks for a judgment over text, so the SQL returns the evidence "
    "and the expected answer is recorded beside it; the validator is not applied"
)
MAX_ROWS = 5_000  # fetched per run; more means the SQL has not reduced to an answer yet
RENDER_ROWS = 500  # rows the validator sees

_FORBIDDEN = re.compile(
    r"^\s*(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|call|do|set)\b",
    re.I,
)

# strips string/identifier literals and comments so a leftover ';' means a second statement
_STRIP_FOR_STMT_CHECK = re.compile(
    r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|--[^\n]*|/\*.*?\*/",
    re.S,
)


def _has_extra_statement(sql: str) -> bool:
    return ";" in _STRIP_FOR_STMT_CHECK.sub("", sql)

DDL = f"""
create table if not exists {PG_META_SCHEMA}.{GOLDEN_TABLE} (
  id               bigserial primary key,
  query_id         text not null,            -- `agnews/1`
  sql              text not null,
  answer_text      text not null,            -- the rendered result the validator judged
  passed           boolean,                  -- null: the SQL errored or the validator could not load
  reason           text not null default '',
  row_count        integer,
  duration_ms      integer,
  error            text,
  note             text not null default '',
  author           text not null,
  db_role          text not null,            -- always dab_agent: the agent's own view of the data
  upstream_commit  text not null,
  created_at       timestamptz not null default now()
);
alter table {PG_META_SCHEMA}.{GOLDEN_TABLE}
  add column if not exists gold_match text not null default '';  -- exact | exact_values | reordered | differs
alter table {PG_META_SCHEMA}.{GOLDEN_TABLE}
  add column if not exists source text not null default '';  -- where the SQL started: '' by hand, or a run's trial
alter table {PG_META_SCHEMA}.{GOLDEN_TABLE}
  add column if not exists kind text not null default 'answer';  -- answer | evidence (a judgment question)
alter table {PG_META_SCHEMA}.{GOLDEN_TABLE}
  add column if not exists expected_answer text not null default '';  -- evidence only: the answer a reader reaches
create table if not exists {PG_META_SCHEMA}.{PROPOSAL_TABLE} (
  id               bigserial primary key,
  query_id         text not null,
  sql              text not null,
  kind             text not null default 'answer',
  expected_answer  text not null default '',
  answer_text      text not null,
  passed           boolean,
  reason           text not null default '',
  gold_match       text not null default '',
  row_count        integer,
  duration_ms      integer,
  error            text,
  replaces         text not null default '',   -- what the trial's Python / llm_extract did
  note             text not null default '',
  author           text not null,
  upstream_commit  text not null,
  created_at       timestamptz not null default now()
);
create index if not exists {PROPOSAL_TABLE}_query on {PG_META_SCHEMA}.{PROPOSAL_TABLE} (query_id, id desc);
comment on table {PG_META_SCHEMA}.{PROPOSAL_TABLE} is
  'Proposed golden SQL, written outside the explorer and checked before it lands. Not a golden: a person '
  'confirms one by saving it in the Golden tab. Append-only; encodes answers, so never granted to dab_agent.';
create index if not exists {GOLDEN_TABLE}_query on {PG_META_SCHEMA}.{GOLDEN_TABLE} (query_id, id desc);
comment on table {PG_META_SCHEMA}.{GOLDEN_TABLE} is
  'Golden SQL, curated in the explorer. Append-only: the newest row per query_id is current. '
  'Encodes answers, so never granted to dab_agent.';
"""


@dataclass
class Execution:
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    duration_ms: int
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def ensure_table() -> None:
    """Create the table if it is missing (as dab_owner, who owns the schema's tables)."""
    with pg.connect() as con:
        con.execute(DDL)  # type: ignore[arg-type,unused-ignore]
        for table in (GOLDEN_TABLE, PROPOSAL_TABLE):
            con.execute(f"revoke all on {PG_META_SCHEMA}.{table} from dab_agent")  # type: ignore[arg-type,unused-ignore]


def _json_safe(v: Any) -> Any:
    if v is None or isinstance(v, bool | int | float | str):
        return v
    if isinstance(v, Decimal):
        return float(v)  # the precision a python analyst (and the gold files) print
    if isinstance(v, dict | list):
        return json.loads(json.dumps(v, default=str))
    return str(v)


def execute(sql: str) -> Execution:
    """Run `sql` as dab_agent in a read-only transaction; fetch at most MAX_ROWS rows."""
    sql = sql.strip()
    t0 = time.time()
    if not sql:
        return Execution([], [], 0, False, 0, "Error: empty SQL")
    if _has_extra_statement(sql.rstrip(";")):
        return Execution([], [], 0, False, 0, "Error: only one statement")
    sql = sql.rstrip(";").strip()
    if not sql:
        return Execution([], [], 0, False, 0, "Error: empty SQL")
    if _FORBIDDEN.match(sql):
        return Execution(
            [], [], 0, False, 0, "Error: only one read-only SELECT (or WITH) statement"
        )
    try:
        with (
            psycopg.connect(settings().agent_database_url, autocommit=True) as con,
            con.transaction(),
        ):
            con.execute("set transaction read only")
            cur = con.execute(sql)  # type: ignore[arg-type,unused-ignore]
            cols = [d.name for d in cur.description or []]
            got = cur.fetchmany(MAX_ROWS + 1)
    except psycopg.Error as e:
        msg = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        return Execution([], [], 0, False, int((time.time() - t0) * 1000), f"Error: {msg}")
    rows = [[_json_safe(v) for v in r] for r in got[:MAX_ROWS]]
    return Execution(cols, rows, len(rows), len(got) > MAX_ROWS, int((time.time() - t0) * 1000))


def _text(v: Any) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    return str(v)


def render(columns: list[str], rows: list[list[Any]]) -> str:
    """The answer text a validator judges: one value alone; otherwise a header line and
    one comma-joined line per row, the shape the gold answers are written in."""
    if not rows:
        return ""
    if len(columns) == 1 and len(rows) == 1:
        return _text(rows[0][0])
    lines = [",".join(columns)]
    lines += [",".join(_text(v) for v in r) for r in rows[:RENDER_ROWS]]
    return "\n".join(lines)


def render_like_gold(columns: list[str], rows: list[list[Any]], gold_text: str) -> str:
    """`render`, but a single value keeps its column name above it when the gold file writes
    the answer that way (a header line naming the same column, then the value). Some validators
    slide a window longer than a bare value (github_repos/2: 18 characters against a 21-character
    window), so the bare value fails although it is the gold's own answer."""
    text = render(columns, rows)
    gold = [ln.strip() for ln in gold_text.lstrip("\ufeff").strip().splitlines() if ln.strip()]
    if (
        len(columns) == 1
        and len(rows) == 1
        and len(gold) == 2
        and "," not in gold[0]
        and _cells_equal(gold[0], columns[0])
    ):
        return f"{columns[0]}\n{text}"
    return text


def _cells_equal(a: str, b: str) -> bool:
    a, b = a.strip().lower(), b.strip().lower()
    if a == b:
        return True
    try:
        x, y = float(a), float(b)
    except ValueError:
        return False
    return abs(x - y) <= 1e-9 * max(1.0, abs(x), abs(y))  # float noise in the last digit


def _lines_equal(xs: list[str], ys: list[str]) -> bool:
    if len(xs) != len(ys):
        return False
    for x, y in zip(xs, ys, strict=True):
        cx, cy = x.split(","), y.split(",")
        if len(cx) != len(cy) or not all(_cells_equal(a, b) for a, b in zip(cx, cy, strict=True)):
            return False
    return True


def _sorted(xs: list[str]) -> list[str]:
    return sorted(x.strip().lower() for x in xs)


def match_gold(columns: list[str], rows: list[list[Any]], gold_text: str) -> dict[str, str]:
    """Does the result recreate the gold answer itself, not just satisfy the validator?

    `exact`: every gold line, in order (a gold header line, when there is one, must match
    the column names too). `exact_values`: the same rows, but the header names differ.
    `reordered`: the same rows in another order. `differs`: anything else. Cells compare
    case-insensitively, and numbers to 1e-9 relative, the noise of a float's last digit."""
    gold = [ln.strip() for ln in gold_text.lstrip("\ufeff").strip().splitlines() if ln.strip()]
    body = [",".join(_text(v) for v in r) for r in rows]
    header = ",".join(columns)
    if not gold:
        return {"match": "differs", "detail": "the gold answer is empty"}
    if not body:
        return {"match": "differs", "detail": f"no rows against {len(gold)} gold line(s)"}
    if _lines_equal(body, gold) or _lines_equal([header, *body], gold):
        return {"match": "exact", "detail": f"all {len(gold)} gold line(s), in order"}
    if len(gold) > 1 and _lines_equal(body, gold[1:]):
        return {
            "match": "exact_values",
            "detail": f"all {len(gold) - 1} gold rows in order; column names {header!r} vs {gold[0]!r}",
        }
    if _sorted(body) in (_sorted(gold), _sorted(gold[1:])):
        return {"match": "reordered", "detail": "the same rows as the gold, in a different order"}
    n_gold = len(gold)
    return {
        "match": "differs",
        "detail": f"{len(body)} result row(s) against {n_gold} gold line(s)",
    }


def _line_key(line: str) -> tuple[str, ...]:
    """A line as difflib should see it: cells compared as `_cells_equal` does, numbers
    rounded to 9 significant digits (a pair that straddles a rounding edge is re-checked
    cell by cell below, so it cannot show as a change)."""
    cells = []
    for c in line.split(","):
        c = c.strip().lower()
        with suppress(ValueError):
            c = f"{float(c):.9g}"
        cells.append(c)
    return tuple(cells)


def gold_diff(columns: list[str], rows: list[list[Any]], gold_text: str) -> list[dict[str, Any]]:
    """The gold against the result, line by line, the way a code review shows a change:
    `del` is a gold line the result lacks, `add` a result line the gold lacks, `eq` a line
    both have. A gold line and a result line that pair up carry `changed`, the indexes of the
    cells that differ. The result side opens with its header only when that lines up better
    with the gold (a gold file may or may not have one)."""
    gold = [ln.strip() for ln in gold_text.lstrip("﻿").strip().splitlines() if ln.strip()]
    body = [",".join(_text(v) for v in r) for r in rows[:RENDER_ROWS]]
    gold_keys = [_line_key(g) for g in gold]

    def matcher(side: list[str]) -> SequenceMatcher[tuple[str, ...]]:
        return SequenceMatcher(None, gold_keys, [_line_key(x) for x in side], autojunk=False)

    sides = [body, [",".join(columns), *body]] if body else [body]
    result = max(sides, key=lambda s: matcher(s).ratio())
    out: list[dict[str, Any]] = []

    def same(gi: int, ri: int) -> None:
        out.append({"op": "eq", "gold": gi + 1, "result": ri + 1, "text": result[ri]})

    for tag, g0, g1, r0, r1 in matcher(result).get_opcodes():
        if tag == "equal":
            for k in range(g1 - g0):
                same(g0 + k, r0 + k)
            continue
        pairs = min(g1 - g0, r1 - r0) if tag == "replace" else 0
        dels: list[dict[str, Any]] = []
        adds: list[dict[str, Any]] = []
        for k in range(max(g1 - g0, r1 - r0)):
            gi = g0 + k if k < g1 - g0 else None
            ri = r0 + k if k < r1 - r0 else None
            if k < pairs and gi is not None and ri is not None:
                gc, rc = gold[gi].split(","), result[ri].split(",")
                width = max(len(gc), len(rc))
                changed = [
                    i
                    for i in range(width)
                    if i >= len(gc) or i >= len(rc) or not _cells_equal(gc[i], rc[i])
                ]
                if not changed:  # equal once compared cell by cell
                    out.extend(dels + adds)
                    dels, adds = [], []
                    same(gi, ri)
                    continue
                dels.append(
                    {
                        "op": "del",
                        "gold": gi + 1,
                        "result": None,
                        "text": gold[gi],
                        "changed": changed,
                    }
                )
                adds.append(
                    {
                        "op": "add",
                        "gold": None,
                        "result": ri + 1,
                        "text": result[ri],
                        "changed": changed,
                    }
                )
            elif gi is not None:
                dels.append({"op": "del", "gold": gi + 1, "result": None, "text": gold[gi]})
            elif ri is not None:
                adds.append({"op": "add", "gold": None, "result": ri + 1, "text": result[ri]})
        out.extend(dels + adds)  # a hunk reads gold lines first, then the result's, as in a review
    return out


_POOL: ProcessPoolExecutor | None = None


def judge_answer(folder: str, query_id: int, answer: str, timeout_s: int = 30) -> dict[str, Any]:
    """The question's own validator on `answer`, in a worker process (the judge is alarm-bounded)."""
    from dab_bench.eval.runner import _judge_in_worker

    global _POOL
    if _POOL is None:
        _POOL = ProcessPoolExecutor(max_workers=1)
    return _POOL.submit(_judge_in_worker, folder, query_id, answer, timeout_s).result(
        timeout=timeout_s + 30
    )


def attempt(
    q: dict[str, Any], folder: str, sql: str, kind: str = "answer"
) -> tuple[dict[str, Any], Execution]:
    """Run `sql` for question `q` (an index row) and judge it: the validator's verdict and the
    comparison with the gold. An evidence golden is run but not judged: its rows are the evidence
    for a judgment the validator cannot check."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    ex = execute(sql)
    answer = render_like_gold(ex.columns, ex.rows, q.get("gold_text", ""))
    if ex.error:
        verdict: dict[str, Any] = {"passed": None, "reason": ex.error}
    elif kind == "evidence":
        verdict = {"passed": None, "reason": EVIDENCE_REASON}
    elif not answer:
        verdict = {"passed": False, "reason": "the query returned no rows"}
    else:
        verdict = judge_answer(folder, int(q["query_id"]), answer)
    if ex.error:
        gold = {"match": "differs", "detail": ex.error}
    elif kind == "evidence":
        gold = {"match": "", "detail": "evidence: not compared with the gold"}
    else:
        gold = match_gold(ex.columns, ex.rows, q["gold_text"])
    out = {
        "execution": ex.as_dict() | {"rows": ex.rows[:200]},  # the page shows 200
        "answer_text": answer,
        "verdict": verdict,
        "gold_match": gold,
        # a line diff against the gold whenever the result does not recreate it
        "gold_diff": []
        if ex.error or kind == "evidence" or gold["match"] in ("exact", "exact_values")
        else gold_diff(ex.columns, ex.rows, q["gold_text"]),
        "kind": kind,
    }
    return out, ex


def _commit() -> str:
    try:
        return str(json.loads(SOURCE_PATH.read_text()).get("commit") or "unknown")
    except (OSError, ValueError):
        return "unknown"


def save(
    query_id: str,
    sql: str,
    ex: Execution,
    answer_text: str,
    verdict: dict[str, Any],
    note: str = "",
    author: str | None = None,
    gold_match: str = "",
    source: str = "",
    kind: str = "answer",
    expected_answer: str = "",
) -> dict[str, Any]:
    """Append one golden. `source` says where the SQL started (empty: typed by hand; else a
    run's trial and call, e.g. `run 2026…_v0_all_haiku · yelp/1/t1 · query_db #3`); a person
    still reviewed, ran and saved it."""
    ensure_table()
    with pg.connect() as con:
        row = con.execute(
            f"""insert into {PG_META_SCHEMA}.{GOLDEN_TABLE}
                (query_id, sql, answer_text, passed, reason, row_count, duration_ms, error,
                 note, author, db_role, upstream_commit, gold_match, source, kind, expected_answer)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'dab_agent', %s, %s, %s, %s, %s)
                returning id, created_at""",  # type: ignore[arg-type,unused-ignore]
            (
                query_id,
                sql.strip(),
                answer_text,
                verdict.get("passed"),
                str(verdict.get("reason") or ""),
                ex.row_count,
                ex.duration_ms,
                ex.error,
                note.strip(),
                author or getpass.getuser(),
                _commit(),
                gold_match,
                source.strip(),
                kind,
                expected_answer.strip(),
            ),
        ).fetchone()
    assert row is not None
    return {"id": row[0], "created_at": row[1].astimezone(UTC).isoformat()}


_COLS = (
    "id",
    "query_id",
    "sql",
    "answer_text",
    "passed",
    "reason",
    "row_count",
    "duration_ms",
    "error",
    "note",
    "author",
    "upstream_commit",
    "created_at",
    "gold_match",
    "source",
    "kind",
    "expected_answer",
)


def _row(r: tuple[Any, ...]) -> dict[str, Any]:
    d = dict(zip(_COLS, r, strict=True))
    if isinstance(d["created_at"], datetime):
        d["created_at"] = d["created_at"].astimezone(UTC).isoformat()
    return d


def current() -> dict[str, dict[str, Any]]:
    """The newest golden per question, with how many saves it took."""
    ensure_table()
    with pg.connect() as con:
        rows = con.execute(
            f"""select distinct on (query_id) {", ".join(_COLS)},
                       count(*) over (partition by query_id)
                from {PG_META_SCHEMA}.{GOLDEN_TABLE}
                order by query_id, id desc"""  # type: ignore[arg-type,unused-ignore]
        ).fetchall()
    return {r[1]: _row(r[:-1]) | {"versions": r[-1]} for r in rows}


def origin(source: str, sources: dict[int, str]) -> str:
    """Where a golden's SQL first came from: a save that started from an earlier golden
    (`golden #n`) is followed back to that golden's own start (a proposal, a run's trial, or
    '' for written by hand)."""
    seen: set[int] = set()
    while (m := re.fullmatch(r"golden #(\d+)", source)) and int(m[1]) in sources:
        if int(m[1]) in seen:
            break
        seen.add(int(m[1]))
        source = sources[int(m[1])]
    return source


def origins() -> dict[str, str]:
    """`origin` of every question's current golden."""
    ensure_table()
    with pg.connect() as con:
        rows = con.execute(
            f"select id, query_id, source from {PG_META_SCHEMA}.{GOLDEN_TABLE} order by id"  # type: ignore[arg-type,unused-ignore]
        ).fetchall()
    sources = {i: src for i, _, src in rows}
    newest = {q: src for _, q, src in rows}  # ordered by id: the last one wins
    return {q: origin(src, sources) for q, src in newest.items()}


def history(query_id: str) -> list[dict[str, Any]]:
    """Every save for one question, newest first."""
    ensure_table()
    with pg.connect() as con:
        rows = con.execute(
            f"select {', '.join(_COLS)} from {PG_META_SCHEMA}.{GOLDEN_TABLE} "
            "where query_id = %s order by id desc",  # type: ignore[arg-type,unused-ignore]
            (query_id,),
        ).fetchall()
    return [_row(r) for r in rows]


# ── proposals: checked SQL waiting for a person to confirm it ────────────────

_PCOLS = (
    "id",
    "query_id",
    "sql",
    "kind",
    "expected_answer",
    "answer_text",
    "passed",
    "reason",
    "gold_match",
    "row_count",
    "duration_ms",
    "error",
    "replaces",
    "note",
    "author",
    "upstream_commit",
    "created_at",
)


def _prow(r: tuple[Any, ...]) -> dict[str, Any]:
    d = dict(zip(_PCOLS, r, strict=True))
    if isinstance(d["created_at"], datetime):
        d["created_at"] = d["created_at"].astimezone(UTC).isoformat()
    return d


def propose(
    query_id: str,
    sql: str,
    out: dict[str, Any],
    ex: Execution,
    replaces: str = "",
    note: str = "",
    expected_answer: str = "",
    author: str = "claude",
) -> dict[str, Any]:
    """Append one proposal (already run and judged by `attempt`). It is not a golden."""
    ensure_table()
    with pg.connect() as con:
        row = con.execute(
            f"""insert into {PG_META_SCHEMA}.{PROPOSAL_TABLE}
                (query_id, sql, kind, expected_answer, answer_text, passed, reason, gold_match,
                 row_count, duration_ms, error, replaces, note, author, upstream_commit)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                returning id, created_at""",  # type: ignore[arg-type,unused-ignore]
            (
                query_id,
                sql.strip(),
                out["kind"],
                expected_answer.strip(),
                out["answer_text"],
                out["verdict"].get("passed"),
                str(out["verdict"].get("reason") or ""),
                out["gold_match"].get("match") or "",
                ex.row_count,
                ex.duration_ms,
                ex.error,
                replaces.strip(),
                note.strip(),
                author,
                _commit(),
            ),
        ).fetchone()
    assert row is not None
    return {"id": row[0], "created_at": row[1].astimezone(UTC).isoformat()}


def proposals() -> dict[str, dict[str, Any]]:
    """The newest proposal per question."""
    ensure_table()
    with pg.connect() as con:
        rows = con.execute(
            f"""select distinct on (query_id) {", ".join(_PCOLS)}
                from {PG_META_SCHEMA}.{PROPOSAL_TABLE}
                order by query_id, id desc"""  # type: ignore[arg-type,unused-ignore]
        ).fetchall()
    return {r[1]: _prow(r) for r in rows}
