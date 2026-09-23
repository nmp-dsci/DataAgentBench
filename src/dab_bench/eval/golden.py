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
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import psycopg

from dab_bench.config import PG_META_SCHEMA, SOURCE_PATH, settings
from dab_bench.data import pg

GOLDEN_TABLE = "golden_sql"
MAX_ROWS = 5_000  # fetched per run; more means the SQL has not reduced to an answer yet
RENDER_ROWS = 500  # rows the validator sees

_FORBIDDEN = re.compile(
    r"^\s*(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|call|do|set)\b",
    re.I,
)

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
        con.execute(f"revoke all on {PG_META_SCHEMA}.{GOLDEN_TABLE} from dab_agent")  # type: ignore[arg-type,unused-ignore]


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
    sql = sql.strip().rstrip(";").strip()
    t0 = time.time()
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
) -> dict[str, Any]:
    """Append one golden. `source` says where the SQL started (empty: typed by hand; else a
    run's trial and call, e.g. `run 2026…_v0_all_haiku · yelp/1/t1 · query_db #3`); a person
    still reviewed, ran and saved it."""
    ensure_table()
    with pg.connect() as con:
        row = con.execute(
            f"""insert into {PG_META_SCHEMA}.{GOLDEN_TABLE}
                (query_id, sql, answer_text, passed, reason, row_count, duration_ms, error,
                 note, author, db_role, upstream_commit, gold_match, source)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'dab_agent', %s, %s, %s)
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
