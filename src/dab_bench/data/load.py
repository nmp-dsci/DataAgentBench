"""`dab data load`: every store of every released dataset into `dataagentbench.<dataset>_<table>`.

Three engines, three paths, one naming rule (`stores.pg_table`):

- **postgres** dumps are plain `pg_dump` files (`CREATE TABLE public.x`,
  `COPY public.x (…) FROM stdin;`). They are streamed statement by statement:
  every `public.<name>` is rewritten to the schema and prefix, owner and
  PG17-only settings are dropped, and COPY blocks go through psycopg's COPY.
- **sqlite / duckdb** files are attached in DuckDB and copied table by table
  through its `postgres` extension.
- **mongo** dumps (`.bson`) are decoded with `bson`; each collection becomes a
  table with one real column per top-level key seen in the first 5 000
  documents (typed when the values agree, `jsonb` for objects and arrays,
  `text` otherwise) plus `doc jsonb` holding the whole document.

Idempotent: a table is dropped and recreated. `dab_load_manifest` records the
source row count per table so `dab data check` can prove the load.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from dab_bench.config import PG_SCHEMA, settings
from dab_bench.data import pg
from dab_bench.data.stores import Store, load_stores, pg_table

MANIFEST_TABLE = "dab_load_manifest"


@dataclass
class LoadedTable:
    dataset: str
    store: str
    source_table: str
    table: str
    source_rows: int


@dataclass
class LoadReport:
    tables: list[LoadedTable] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------------- postgres dumps

_PUBLIC = re.compile(r'\bpublic\.(?:"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*))')
_CREATE_INDEX = re.compile(r"^(CREATE (?:UNIQUE )?INDEX )(?:\"([^\"]+)\"|(\w+))( ON )", re.I)
_DROP_STATEMENTS = (
    re.compile(r"^ALTER TABLE .* OWNER TO ", re.I),
    re.compile(r"^SET transaction_timeout", re.I),
    re.compile(r"^CREATE SCHEMA public", re.I),
    re.compile(r"^COMMENT ON SCHEMA public", re.I),
    re.compile(r"^ALTER SCHEMA public", re.I),
    re.compile(r"^(CREATE|ALTER) EXTENSION", re.I),
    re.compile(r"^COMMENT ON EXTENSION", re.I),
)


def rewrite_statement(stmt: str, dataset: str) -> str | None:
    """One pg_dump statement, re-pointed at the schema; None when it must be dropped."""
    head = stmt.lstrip()
    for pat in _DROP_STATEMENTS:
        if pat.match(head):
            return None

    def repl(m: re.Match[str]) -> str:
        name = m.group(1) or m.group(2)
        return f'{PG_SCHEMA}."{pg_table(dataset, name)}"'

    out = _PUBLIC.sub(repl, stmt)
    m = _CREATE_INDEX.match(out.lstrip())
    if m:
        name = m.group(2) or m.group(3)
        out = out.replace(m.group(0), f'{m.group(1)}"{pg_table(dataset, name)}"{m.group(4)}', 1)
    return out


def _statements(lines: Iterator[str]) -> Iterator[tuple[str, Iterator[str] | None]]:
    """Yield (statement, copy_lines) pairs from a plain pg_dump stream."""
    buf: list[str] = []
    for line in lines:
        s = line.rstrip("\n")
        if not buf and (not s.strip() or s.startswith("--")):
            continue
        buf.append(s)
        if s.rstrip().endswith(";"):
            stmt = "\n".join(buf)
            buf = []
            if re.match(r"^COPY\s", stmt.lstrip(), re.I) and stmt.rstrip().upper().endswith(
                "FROM STDIN;"
            ):
                yield stmt, _copy_block(lines)
            else:
                yield stmt, None
    if buf:
        yield "\n".join(buf), None


def _copy_block(lines: Iterator[str]) -> Iterator[str]:
    for line in lines:
        if line.rstrip("\n") == "\\.":
            return
        yield line


_CREATE_TABLE = re.compile(r"^CREATE TABLE\s+(\S+)", re.I)
_COPY_TABLE = re.compile(r"^COPY\s+(\S+)", re.I)


_SCRIPT_CREATE = re.compile(
    r'^(CREATE TABLE(?: IF NOT EXISTS)?\s+)("?)([A-Za-z_][A-Za-z0-9_]*)("?)', re.M
)
_SCRIPT_INSERT = re.compile(r'^(INSERT INTO\s+)("?)([A-Za-z_][A-Za-z0-9_]*)("?)', re.M)


def is_pg_dump(path: Path) -> bool:
    """A `pg_dump` plain file (schema-qualified, COPY blocks) vs a hand-written SQL script."""
    with path.open("r", encoding="utf-8", errors="replace") as f:
        head = "".join(next(f, "") for _ in range(60))
    return "public." in head or "PostgreSQL database dump" in head


def load_sql_script(store: Store, con: psycopg.Connection[Any], rep: LoadReport) -> None:
    """Unqualified `CREATE TABLE x (…); INSERT INTO x VALUES (…);` scripts (crmarenapro's support.sql).

    Statement starts are re-pointed at the schema; the script then runs as one
    batch, so a store loads entirely or not at all.
    """
    text = store.path.read_text(encoding="utf-8", errors="replace")
    tables: dict[str, int] = {}

    def create(m: re.Match[str]) -> str:
        t = pg_table(store.dataset, m.group(3))
        tables.setdefault(t, 0)
        return f'{m.group(1)}{PG_SCHEMA}."{t}"'

    def insert(m: re.Match[str]) -> str:
        t = pg_table(store.dataset, m.group(3))
        tables[t] = tables.get(t, 0) + 1
        return f'{m.group(1)}{PG_SCHEMA}."{t}"'

    text = _SCRIPT_CREATE.sub(create, text)
    text = _SCRIPT_INSERT.sub(insert, text)
    for t in tables:
        pg.drop_table(con, t)
    con.execute(text)  # type: ignore[arg-type,unused-ignore]
    for t, n in tables.items():
        rep.tables.append(
            LoadedTable(store.dataset, store.name, t.removeprefix(store.dataset + "_"), t, n)
        )


def load_pg_dump(store: Store, con: psycopg.Connection[Any], rep: LoadReport) -> None:
    if not is_pg_dump(store.path):
        load_sql_script(store, con, rep)
        return
    created: dict[str, int] = {}
    with store.path.open("r", encoding="utf-8", errors="replace") as f, con.cursor() as cur:
        it = iter(f)
        for stmt, copy_lines in _statements(it):
            new = rewrite_statement(stmt, store.dataset)
            if new is None:
                continue
            if copy_lines is not None:
                m = _COPY_TABLE.match(new.lstrip())
                target = m.group(1) if m else "?"
                n = 0
                with cur.copy(new.rstrip().rstrip(";")) as cp:
                    for line in copy_lines:
                        cp.write(line)
                        n += 1
                created[target] = created.get(target, 0) + n
                continue
            m = _CREATE_TABLE.match(new.lstrip())
            if m:
                cur.execute(f"DROP TABLE IF EXISTS {m.group(1)} CASCADE")
                created.setdefault(m.group(1), 0)
            cur.execute(new)  # type: ignore[arg-type,unused-ignore]
    for target, n in created.items():
        table = target.split(".")[-1].strip('"')
        src = table.removeprefix(store.dataset + "_")
        rep.tables.append(LoadedTable(store.dataset, store.name, src, table, n))


# ----------------------------------------------------------------------------- sqlite / duckdb


def _pg_attach_string() -> str:
    """libpq keyword form of DATABASE_URL for DuckDB's postgres extension."""
    from urllib.parse import urlparse

    u = urlparse(settings().database_url)
    parts = [f"dbname={u.path.lstrip('/')}"]
    if u.hostname:
        parts.append(f"host={u.hostname}")
    if u.port:
        parts.append(f"port={u.port}")
    if u.username:
        parts.append(f"user={u.username}")
    if u.password:
        parts.append(f"password={u.password}")
    return " ".join(parts)


def load_file_db(store: Store, con: psycopg.Connection[Any], rep: LoadReport) -> None:
    import duckdb

    ddb = duckdb.connect()
    for ext in ("sqlite", "postgres"):
        ddb.install_extension(ext)
        ddb.load_extension(ext)
    if store.engine == "sqlite":
        ddb.execute(f"ATTACH '{store.path}' AS src (TYPE sqlite, READ_ONLY)")
    else:
        ddb.execute(f"ATTACH '{store.path}' AS src (READ_ONLY)")
    ddb.execute(f"ATTACH '{_pg_attach_string()}' AS pg (TYPE postgres)")
    tables = [
        r[0]
        for r in ddb.execute(
            "SELECT table_name FROM duckdb_tables() WHERE database_name = 'src' "
            "AND schema_name = 'main' ORDER BY table_name"
        ).fetchall()
    ]
    for t in tables:
        target = pg_table(store.dataset, t)
        # drop through DuckDB, not psycopg: DuckDB caches the attached catalog at ATTACH time and a
        # table dropped behind its back is recreated empty (seen on the crmarenapro reload)
        ddb.execute(f'DROP TABLE IF EXISTS pg.{PG_SCHEMA}."{target}"')
        n = int(ddb.execute(f'SELECT count(*) FROM src."{t}"').fetchone()[0])  # type: ignore[index]
        ddb.execute(f'CREATE TABLE pg.{PG_SCHEMA}."{target}" AS SELECT * FROM src."{t}"')
        rep.tables.append(LoadedTable(store.dataset, store.name, t, target, n))
    ddb.close()


# ----------------------------------------------------------------------------- mongo dumps

_SAMPLE = 5000


def _pg_type(values: list[Any]) -> str:
    kinds = {type(v) for v in values if v is not None}
    if not kinds:
        return "text"
    if kinds <= {bool}:
        return "boolean"
    if kinds <= {int}:
        return "bigint"
    if kinds <= {int, float}:
        return "double precision"
    if kinds <= {datetime}:
        return "timestamptz"
    if kinds <= {dict, list}:
        return "jsonb"
    return "text"


def _coerce(v: Any, typ: str) -> Any:
    if v is None:
        return None
    if typ == "jsonb":
        return Jsonb(_plain(v))
    if typ == "text":
        return v if isinstance(v, str) else _plain(v) if isinstance(v, dict | list) else str(v)
    return v


def _plain(v: Any) -> Any:
    """bson types → JSON-serialisable."""
    from bson import ObjectId

    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return v


def _bson_docs(path: Path) -> Iterator[dict[str, Any]]:
    from bson import decode_file_iter

    with path.open("rb") as f:
        yield from decode_file_iter(f)


def load_mongo(store: Store, con: psycopg.Connection[Any], rep: LoadReport) -> None:
    db_dir = store.path / (store.db_name or "")
    if not db_dir.is_dir():
        candidates = [p for p in store.path.iterdir() if p.is_dir()]
        if len(candidates) != 1:
            raise FileNotFoundError(f"no mongo db folder under {store.path}")
        db_dir = candidates[0]
    for bson_path in sorted(db_dir.glob("*.bson")):
        coll = bson_path.stem
        target = pg_table(store.dataset, coll)
        # pass 1: the column set and types, from the head of the file
        seen: dict[str, list[Any]] = {}
        for i, d in enumerate(_bson_docs(bson_path)):
            if i >= _SAMPLE:
                break
            for k, v in d.items():
                seen.setdefault(str(k), []).append(v)
        cols = [(k, "text" if k == "_id" else _pg_type(vs)) for k, vs in seen.items()]
        pg.drop_table(con, target)
        ddl = ", ".join(f'"{k}" {t}' for k, t in cols) + ", doc jsonb"
        con.execute(f'CREATE TABLE {PG_SCHEMA}."{target}" ({ddl})')
        names = [k for k, _ in cols] + ["doc"]
        types = dict(cols)
        n = 0
        with (
            con.cursor() as cur,
            cur.copy(
                f'COPY {PG_SCHEMA}."{target}" ({", ".join(chr(34) + c + chr(34) for c in names)}) FROM STDIN'
            ) as cp,
        ):
            for d in _bson_docs(bson_path):
                row: list[Any] = []
                for k, _ in cols:
                    v = d.get(k)
                    if k == "_id":
                        row.append(str(v) if v is not None else None)
                    else:
                        try:
                            row.append(_coerce(v, types[k]))
                        except Exception:  # noqa: BLE001 - a stray value must not sink 6M rows
                            row.append(None)
                row.append(Jsonb(_plain(d)))
                cp.write_row(row)
                n += 1
        rep.tables.append(LoadedTable(store.dataset, store.name, coll, target, n))


# ----------------------------------------------------------------------------- driver


def _ensure_manifest(con: psycopg.Connection[Any]) -> None:
    con.execute(
        f"""CREATE TABLE IF NOT EXISTS {PG_SCHEMA}."{MANIFEST_TABLE}" (
            dataset text not null, store text not null, source_table text not null,
            "table" text primary key, source_rows bigint, loaded_at timestamptz not null)"""
    )


def _record(con: psycopg.Connection[Any], t: LoadedTable) -> None:
    con.execute(
        f'INSERT INTO {PG_SCHEMA}."{MANIFEST_TABLE}" (dataset, store, source_table, "table", source_rows, loaded_at) '
        'VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT ("table") DO UPDATE SET '
        "dataset = excluded.dataset, store = excluded.store, source_table = excluded.source_table, "
        "source_rows = excluded.source_rows, loaded_at = excluded.loaded_at",
        (t.dataset, t.store, t.source_table, t.table, t.source_rows, datetime.now(UTC)),
    )


def load_store(store: Store, con: psycopg.Connection[Any], rep: LoadReport) -> None:
    if store.engine == "postgres":
        load_pg_dump(store, con, rep)
    elif store.engine in {"sqlite", "duckdb"}:
        load_file_db(store, con, rep)
    elif store.engine == "mongo":
        load_mongo(store, con, rep)
    else:
        raise ValueError(f"unknown engine {store.engine} for {store.dataset}/{store.name}")


def load(
    datasets: list[str] | None = None,
    stores: list[Store] | None = None,
    on_progress: Any = None,
) -> LoadReport:
    rep = LoadReport()
    stores = stores if stores is not None else load_stores()
    if datasets:
        stores = [s for s in stores if s.dataset in set(datasets)]
    with pg.connect() as con:
        _ensure_manifest(con)
        for s in stores:
            if not s.path.exists():
                rep.errors.append(
                    f"{s.dataset}/{s.name}: missing {s.path} (run `dab data download`)"
                )
                continue
            before = len(rep.tables)
            try:
                load_store(s, con, rep)
            except Exception as e:  # noqa: BLE001 - one bad store must not stop the other 11 datasets
                rep.errors.append(f"{s.dataset}/{s.name}: {type(e).__name__}: {e}"[:400])
                continue
            new = rep.tables[before:]
            names = [t.table for t in new]
            dupes = {n for n in names if names.count(n) > 1}
            if dupes:
                rep.errors.append(f"{s.dataset}/{s.name}: table name collision {sorted(dupes)}")
            for t in new:
                _record(con, t)
            if on_progress:
                on_progress(s, new)
    return rep


@dataclass(frozen=True)
class CheckRow:
    dataset: str
    table: str
    source_rows: int | None
    live_rows: int
    ok: bool


def check(datasets: list[str] | None = None) -> list[CheckRow]:
    """Every recorded table's live row count against the source count."""
    out: list[CheckRow] = []
    with pg.connect() as con:
        _ensure_manifest(con)
        rows = con.execute(
            f'SELECT dataset, "table", source_rows FROM {PG_SCHEMA}."{MANIFEST_TABLE}" ORDER BY dataset, "table"'
        ).fetchall()
        live = set(pg.list_tables(con))
        for dataset, table, src in rows:
            if datasets and dataset not in datasets:
                continue
            n = pg.count_rows(con, table) if table in live else 0
            out.append(
                CheckRow(dataset, table, src, n, table in live and (src is None or src == n))
            )
    return out
