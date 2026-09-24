"""`dab data load-questions`: the committed question set copied into Postgres, for humans.

`data/index/queries.json` remains the record — this is a derived copy, dropped and
rebuilt on every run, so it can never be the thing anyone edits. It exists so the
questions, their gold and their validators can be joined against the benchmark data
in dbgate or any SQL client instead of grepping JSON.

It lives in its own schema, `dataagentbench_meta`, and that is the whole point:
`dataagentbench` grants SELECT to `dab_agent` by default (`infra/roles.sql`), so a
question table placed there would hand the agent every gold answer. Nothing is
granted here, `dab_agent`'s `search_path` does not include it, and
`tests/test_meta.py` asserts the agent role is refused.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg

from dab_bench.config import PG_META_SCHEMA, QUERIES_PATH, SOURCE_PATH
from dab_bench.data import pg

QUESTIONS_TABLE = "queries"

# The schema itself is made by `dab data init` as the superuser (infra/roles.sql):
# dab_owner may create tables in it but not create the schema in this database.
DDL = f"""
drop table if exists {PG_META_SCHEMA}.{QUESTIONS_TABLE};
create table {PG_META_SCHEMA}.{QUESTIONS_TABLE} (
  id                text primary key,
  dataset_key       text not null,
  query_id          integer not null,
  question          text not null,
  gold_text         text not null,
  gold_lines        integer not null,
  validator_style   text not null,
  validator_lines   integer not null,
  reads_gold_file   boolean not null,
  validator_source  text not null,
  released          boolean not null,
  on_site           boolean,
  site_text_matches boolean,
  footnote          text,
  upstream_commit   text not null,
  loaded_at         timestamptz not null
);
comment on table {PG_META_SCHEMA}.{QUESTIONS_TABLE} is
  'Derived copy of data/index/queries.json. The JSON is the record; rebuild with '
  '`dab data load-questions`. Never granted to dab_agent: it holds every gold answer.';
"""

COLUMNS = (
    "id",
    "dataset_key",
    "query_id",
    "question",
    "gold_text",
    "gold_lines",
    "validator_style",
    "validator_lines",
    "reads_gold_file",
    "validator_source",
    "released",
    "on_site",
    "site_text_matches",
    "footnote",
    "upstream_commit",
    "loaded_at",
)


@dataclass(frozen=True)
class MetaLoad:
    rows: int
    schema: str
    table: str
    upstream_commit: str


def _rows(commit: str, now: datetime) -> list[tuple[Any, ...]]:
    out = []
    for q in json.loads(QUERIES_PATH.read_text()):
        v = q.get("validator") or {}
        out.append(
            (
                q["id"],
                q["dataset_key"],
                int(q["query_id"]),
                q["question"],
                q["gold_text"],
                int(q["gold_lines"]),
                v.get("style", ""),
                int(v.get("lines", 0)),
                bool(v.get("reads_gold_file", False)),
                v.get("source", ""),
                bool(q.get("released", True)),
                q.get("on_site"),
                q.get("site_text_matches"),
                q.get("footnote"),
                commit,
                now,
            )
        )
    return out


def load_questions(con: psycopg.Connection[Any] | None = None) -> MetaLoad:
    """Drop and rebuild the question table from the committed index. Idempotent."""
    commit = str(json.loads(SOURCE_PATH.read_text()).get("commit", ""))
    rows = _rows(commit, datetime.now(UTC))
    owned = con is None
    con = con or pg.connect()
    try:
        con.execute(DDL)  # type: ignore[arg-type,unused-ignore]
        # The schema is for people, never for the agent; dataagentbench's default
        # grant does not reach here, and this makes that explicit and re-runnable.
        con.execute(f"revoke all on schema {PG_META_SCHEMA} from dab_agent")
        con.execute(f"revoke all on all tables in schema {PG_META_SCHEMA} from dab_agent")
        placeholders = ", ".join(["%s"] * len(COLUMNS))
        with con.cursor() as cur:
            cur.executemany(
                f"insert into {PG_META_SCHEMA}.{QUESTIONS_TABLE} "
                f"({', '.join(COLUMNS)}) values ({placeholders})",
                rows,
            )
    finally:
        if owned:
            con.close()
    return MetaLoad(
        rows=len(rows), schema=PG_META_SCHEMA, table=QUESTIONS_TABLE, upstream_commit=commit
    )
