"""`dab context build`: the generated half of the context pack, from the loaded Postgres.

One folder per dataset under `data/context/<dataset>/`, plain code, no model:

- `tables.json`   store → source table → Postgres table, columns and types (what the tools read)
- `schema.md`     per store: tables, columns with types, keys, row counts
- `profile.json`  per column: null rate, distinct count, min/max, top values for low-cardinality text
- `samples/<table>.md`  five rows per table, wide text cut at 200 chars
- `joins.md`      measured overlap for candidate key pairs across tables (Scout's "join overlaps")
- `description.txt` · `hints.txt`  the upstream files, byte-identical

Deterministic and committed, so a run's context is versioned with the code
(`context_sha` on every result row). The curated half — `summary.md` and
`pitfalls.md` — is written by the curator agent (`context/curate.py`), never here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg

from dab_bench.config import CONTEXT_DIR, DATASETS_PATH, PG_SCHEMA
from dab_bench.data import pg
from dab_bench.data.load import MANIFEST_TABLE

SAMPLE_ROWS = 5
TEXT_CUT = 200
TOP_VALUES = 10
LOW_CARDINALITY = 50
PROFILE_SAMPLE_ROWS = 200_000  # tables above this are profiled on a sample
JOIN_SAMPLE_ROWS = 200_000
MAX_JOIN_PAIRS = 150

NUMERIC = {"smallint", "integer", "bigint", "double precision", "real", "numeric", "decimal"}
TEMPORAL = {"date", "timestamp without time zone", "timestamp with time zone"}


@dataclass
class TableMeta:
    store: str
    source_table: str
    table: str
    rows: int
    columns: list[tuple[str, str]]
    primary_key: list[str] = field(default_factory=list)
    foreign_keys: list[dict[str, str]] = field(default_factory=list)


def _tables(con: psycopg.Connection[Any], dataset: str) -> list[TableMeta]:
    rows = con.execute(
        f'SELECT store, source_table, "table", source_rows FROM {PG_SCHEMA}."{MANIFEST_TABLE}" '
        'WHERE dataset = %s ORDER BY store, "table"',
        (dataset,),
    ).fetchall()
    out: list[TableMeta] = []
    live = set(pg.list_tables(con))
    for store, src, table, n in rows:
        if table not in live:
            continue
        cols = pg.columns(con, table)
        pk = [
            r[0]
            for r in con.execute(
                "SELECT kcu.column_name FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name "
                "AND tc.table_schema = kcu.table_schema WHERE tc.table_schema = %s AND tc.table_name = %s "
                "AND tc.constraint_type = 'PRIMARY KEY' ORDER BY kcu.ordinal_position",
                (PG_SCHEMA, table),
            ).fetchall()
        ]
        fks = [
            {"column": r[0], "ref_table": r[1], "ref_column": r[2]}
            for r in con.execute(
                "SELECT kcu.column_name, ccu.table_name, ccu.column_name "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name "
                "JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name "
                "WHERE tc.table_schema = %s AND tc.table_name = %s AND tc.constraint_type = 'FOREIGN KEY'",
                (PG_SCHEMA, table),
            ).fetchall()
        ]
        out.append(TableMeta(store, src, table, int(n or 0), cols, pk, fks))
    return out


FAMILY_MIN = 10


@dataclass
class Family:
    store: str
    members: list[str]  # Postgres table names
    representative: TableMeta
    union_table: str | None  # the `<dataset>_<store>_all` table when the load materialised it


def collapse_families(tables: list[TableMeta]) -> tuple[list[TableMeta], list[Family]]:
    """Tables that share a store and a column signature, ten or more of them, become one family.

    stockmarket ships one table per ticker (2 753); the pack describes the family once and
    points at the union table the load built (`*_all`, with a `_table` column).
    """
    groups: dict[tuple[str, tuple[tuple[str, str], ...]], list[TableMeta]] = {}
    for t in tables:
        groups.setdefault((t.store, tuple(t.columns)), []).append(t)
    kept: list[TableMeta] = []
    families: list[Family] = []
    union_by_store = {t.store: t.table for t in tables if t.source_table.startswith("*(")}
    for (store, _sig), ts in groups.items():
        if len(ts) >= FAMILY_MIN:
            rep = max(ts, key=lambda t: t.rows)
            families.append(Family(store, [t.table for t in ts], rep, union_by_store.get(store)))
        else:
            kept.extend(ts)
    return kept, families


def _q(table: str) -> str:
    return f'{PG_SCHEMA}."{table}"'


def _sample_clause(rows: int, cap: int) -> str:
    if rows <= cap:
        return ""
    pct = max(0.01, min(100.0, 100.0 * cap / rows))
    return f" TABLESAMPLE SYSTEM ({pct:.3f})"


def _fmt(v: Any) -> str:
    if v is None:
        return "NULL"
    s = json.dumps(v, default=str, ensure_ascii=False) if isinstance(v, dict | list) else str(v)
    s = s.replace("\n", " ").replace("|", "\\|")
    return s if len(s) <= TEXT_CUT else s[:TEXT_CUT] + "…"


def profile_table(con: psycopg.Connection[Any], t: TableMeta) -> dict[str, Any]:
    src = _q(t.table) + _sample_clause(t.rows, PROFILE_SAMPLE_ROWS)
    prof: dict[str, Any] = {}
    for col, typ in t.columns:
        if col == "doc" and typ == "jsonb":
            prof[col] = {
                "type": typ,
                "note": "the whole source document; the other columns are its top-level keys",
            }
            continue
        c = f'"{col}"'
        entry: dict[str, Any] = {"type": typ}
        try:
            if typ in NUMERIC or typ in TEMPORAL:
                r = con.execute(
                    f"SELECT count(*), count({c}), count(distinct {c}), min({c}), max({c}) FROM {src}"
                ).fetchone()
            else:
                r = con.execute(
                    f"SELECT count(*), count({c}), count(distinct {c}::text), NULL, NULL FROM {src}"
                ).fetchone()
            n, nn, nd, mn, mx = r if r else (0, 0, 0, None, None)
            entry["null_rate"] = round(1 - (nn / n), 4) if n else None
            entry["distinct"] = int(nd)
            if mn is not None:
                entry["min"], entry["max"] = _fmt(mn), _fmt(mx)
            if (
                typ not in NUMERIC
                and typ not in TEMPORAL
                and typ != "jsonb"
                and 0 < nd <= LOW_CARDINALITY
            ):
                top = con.execute(
                    f"SELECT {c}::text, count(*) FROM {src} WHERE {c} IS NOT NULL "
                    f"GROUP BY 1 ORDER BY 2 DESC LIMIT {TOP_VALUES}"
                ).fetchall()
                entry["top"] = [[_fmt(v), int(k)] for v, k in top]
            if typ == "jsonb":
                keys = con.execute(
                    f"SELECT k, count(*) FROM (SELECT jsonb_object_keys({c}) AS k FROM {src} "
                    f"WHERE jsonb_typeof({c}) = 'object' LIMIT 50000) s GROUP BY k ORDER BY 2 DESC LIMIT 40"
                ).fetchall()
                entry["json_keys"] = {str(k): int(n) for k, n in keys}
            if t.rows > PROFILE_SAMPLE_ROWS:
                entry["sampled"] = True
        except Exception as e:  # noqa: BLE001 - one odd column must not stop the profile
            entry["error"] = f"{type(e).__name__}: {e}"[:200]
            con.rollback() if not con.autocommit else None
        prof[col] = entry
    return prof


def sample_table(con: psycopg.Connection[Any], t: TableMeta) -> str:
    cols = [c for c, typ in t.columns if not (c == "doc" and typ == "jsonb")]
    rows = con.execute(
        f"SELECT {', '.join(chr(34) + c + chr(34) for c in cols)} FROM {_q(t.table)} LIMIT {SAMPLE_ROWS}"
    ).fetchall()
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    body = "".join("| " + " | ".join(_fmt(v) for v in r) + " |\n" for r in rows)
    return f"# {t.table} ({t.rows:,} rows) · first {SAMPLE_ROWS}\n\n" + head + body


_KEYISH = re.compile(r"(id|ref|key|code|isbn|name|symbol|ticker|barcode)", re.I)
_GENERIC = {"id", "_id", "key"}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower()).replace("ref", "id")


def _aliases(t: TableMeta, col: str) -> set[str]:
    """Names a column can be joined under: itself, and `<table>id` when it is a bare id."""
    dataset_prefix = t.table.split("_", 1)[0] + "_"
    short = _norm(t.table.removeprefix(dataset_prefix))
    n = _norm(col)
    out = {n}
    if col.lower() in _GENERIC or n in {"id", "key"}:
        out = {short + "id", short[:-1] + "id" if short.endswith("s") else short + "id"}
    return out


def candidate_pairs(tables: list[TableMeta]) -> list[tuple[TableMeta, str, TableMeta, str]]:
    """Column pairs across different tables whose names name the same key.

    Key-like columns first (`AccountId` in `orders` pairs with `Id` in `account`, a bare
    id being known by its table's name; `business_ref` pairs with `business_id`), then
    any two columns with the same normalised name (`System`, `Version`, `Index`). Two
    bare `Id` columns never pair with each other.
    """
    cols = [(t, c) for t in tables for c, typ in t.columns if typ != "jsonb" and c != "_id"]
    keyish: list[tuple[TableMeta, str, TableMeta, str]] = []
    same: list[tuple[TableMeta, str, TableMeta, str]] = []
    for i, (ta, ca) in enumerate(cols):
        for tb, cb in cols[i + 1 :]:
            if ta.table == tb.table:
                continue
            if ca.lower() in _GENERIC and cb.lower() in _GENERIC:
                continue
            if (_KEYISH.search(ca) or _KEYISH.search(cb)) and _aliases(ta, ca) & _aliases(tb, cb):
                keyish.append((ta, ca, tb, cb))
            elif _norm(ca) == _norm(cb):
                same.append((ta, ca, tb, cb))
    return (keyish + same)[:MAX_JOIN_PAIRS]


_NORMALISE = "lower(regexp_replace(trim({c}::text), '^[#]+', ''))"
_DIGITS = "nullif(regexp_replace({c}::text, '[^0-9]', '', 'g'), '')"


def measure_join(
    con: psycopg.Connection[Any], ta: TableMeta, ca: str, tb: TableMeta, cb: str
) -> dict[str, Any]:
    """Share of distinct A values found in B, raw and after trim/'#'-strip/lower-case."""
    a = _q(ta.table) + _sample_clause(ta.rows, JOIN_SAMPLE_ROWS)
    b = _q(tb.table) + _sample_clause(tb.rows, JOIN_SAMPLE_ROWS)
    out: dict[str, Any] = {"a": f'{ta.table}."{ca}"', "b": f'{tb.table}."{cb}"'}
    for label, expr in (("raw", "{c}::text"), ("normalised", _NORMALISE), ("digits", _DIGITS)):
        ea, eb = expr.format(c=f'"{ca}"'), expr.format(c=f'"{cb}"')
        r = con.execute(
            f'WITH a AS (SELECT DISTINCT {ea} AS v FROM {a} WHERE "{ca}" IS NOT NULL), '
            f'b AS (SELECT DISTINCT {eb} AS v FROM {b} WHERE "{cb}" IS NOT NULL) '
            "SELECT (SELECT count(*) FROM a), (SELECT count(*) FROM a JOIN b USING (v))"
        ).fetchone()
        na, nab = (int(r[0]), int(r[1])) if r else (0, 0)
        out[label] = {"distinct_a": na, "matched": nab, "share": round(nab / na, 4) if na else None}
    return out


def render_schema(
    dataset: str, tables: list[TableMeta], families: list[Family] | None = None
) -> str:
    lines = [
        f"# {dataset} — schema",
        "",
        f"Postgres schema `{PG_SCHEMA}`; every table is `{dataset}_<table>`.",
        "",
    ]
    by_store: dict[str, list[TableMeta]] = {}
    for t in tables:
        by_store.setdefault(t.store, []).append(t)
    for f in families or []:
        by_store.setdefault(f.store, [])
    for store, ts in by_store.items():
        lines.append(f"## store `{store}`")
        for f in [f for f in (families or []) if f.store == store]:
            lines.append(
                f"\n### family of {len(f.members):,} tables with identical columns "
                f"(e.g. `{f.representative.table}`, {f.representative.rows:,} rows; members: "
                + ", ".join(f"`{m}`" for m in sorted(f.members)[:8])
                + ", …)"
            )
            if f.union_table:
                lines.append(
                    f"Query them together through `{f.union_table}`: the same columns plus "
                    f"`_table` (the member name without the `{dataset}_` prefix, e.g. the ticker)."
                )
            lines.append("")
            lines.append("| column | type |")
            lines.append("|---|---|")
            for c, typ in f.representative.columns:
                lines.append(f"| {c} | {typ} |")
        for t in ts:
            lines.append(f"\n### `{t.table}` — {t.rows:,} rows (source table `{t.source_table}`)")
            if t.primary_key:
                lines.append(f"primary key: {', '.join(t.primary_key)}")
            for fk in t.foreign_keys:
                lines.append(f"foreign key: {fk['column']} → {fk['ref_table']}.{fk['ref_column']}")
            lines.append("")
            lines.append("| column | type |")
            lines.append("|---|---|")
            for c, typ in t.columns:
                lines.append(f"| {c} | {typ} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def render_joins(dataset: str, joins: list[dict[str, Any]]) -> str:
    lines = [
        f"# {dataset} — measured join overlaps",
        "",
        "Share of distinct values of column A found in column B: raw, after `trim`/`#`-strip/lower-case, "
        "and on the digits alone (for keys that differ only by a textual prefix). "
        "Measured on the live tables (sampled above 200k rows). A share near 1.0 is a usable join key; "
        "a normalised share much higher than raw means the keys need cleaning first.",
        "",
        "| A | B | distinct A | raw share | normalised share | digits-only share |",
        "|---|---|---|---|---|---|",
    ]
    for j in sorted(joins, key=lambda j: -(j["normalised"]["share"] or 0)):
        lines.append(
            f"| {j['a']} | {j['b']} | {j['raw']['distinct_a']:,} | "
            f"{j['raw']['share'] if j['raw']['share'] is not None else '—'} | "
            f"{j['normalised']['share'] if j['normalised']['share'] is not None else '—'} | "
            f"{j.get('digits', {}).get('share') if j.get('digits', {}).get('share') is not None else '—'} |"
        )
    return "\n".join(lines) + "\n"


@dataclass
class BuildResult:
    dataset: str
    tables: int
    joins: int
    path: Path


def build_dataset(
    dataset: str, con: psycopg.Connection[Any], out_dir: Path = CONTEXT_DIR
) -> BuildResult:
    meta = {d["key"]: d for d in json.loads(DATASETS_PATH.read_text())}[dataset]
    all_tables = _tables(con, dataset)
    if not all_tables:
        raise RuntimeError(
            f"{dataset}: no loaded tables (run `dab data load --datasets {dataset}`)"
        )
    tables, families = collapse_families(all_tables)
    d = out_dir / dataset
    if (d / "samples").is_dir():
        for old in (d / "samples").glob("*.md"):
            old.unlink()
    (d / "samples").mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = [
        {
            "store": t.store,
            "source_table": t.source_table,
            "table": t.table,
            "rows": t.rows,
            "columns": [{"name": c, "type": typ} for c, typ in t.columns],
            "primary_key": t.primary_key,
            "foreign_keys": t.foreign_keys,
        }
        for t in tables
    ]
    for f in families:
        entries.append(
            {
                "store": f.store,
                "source_table": f"*({len(f.members)} tables)",
                "table": f.representative.table,
                "rows": f.representative.rows,
                "columns": [{"name": c, "type": typ} for c, typ in f.representative.columns],
                "primary_key": [],
                "foreign_keys": [],
                "family": {"members": sorted(f.members), "union_table": f.union_table},
            }
        )
    (d / "tables.json").write_text(json.dumps(entries, indent=1) + "\n")
    (d / "schema.md").write_text(render_schema(dataset, tables, families))
    tables = tables + [f.representative for f in families]
    profile = {t.table: profile_table(con, t) for t in tables}
    (d / "profile.json").write_text(json.dumps(profile, indent=1, ensure_ascii=False) + "\n")
    for t in tables:
        (d / "samples" / f"{t.table}.md").write_text(sample_table(con, t))
    joins: list[dict[str, Any]] = []
    for ta, ca, tb, cb in candidate_pairs(tables):
        try:
            joins.append(measure_join(con, ta, ca, tb, cb))
        except Exception as e:  # noqa: BLE001 - a bad pair is skipped, not fatal
            joins.append(
                {
                    "a": f"{ta.table}.{ca}",
                    "b": f"{tb.table}.{cb}",
                    "error": str(e)[:200],
                    "raw": {"distinct_a": 0, "share": None},
                    "normalised": {"share": None},
                }
            )
    (d / "joins.md").write_text(render_joins(dataset, [j for j in joins if "error" not in j]))
    (d / "joins.json").write_text(json.dumps(joins, indent=1) + "\n")
    (d / "description.txt").write_text(meta.get("description") or "")
    (d / "hints.txt").write_text(meta.get("hints") or "")
    return BuildResult(dataset, len(tables), len(joins), d)


def build(datasets: list[str] | None = None) -> list[BuildResult]:
    keys = [d["key"] for d in json.loads(DATASETS_PATH.read_text()) if d.get("released", True)]
    if datasets:
        keys = [k for k in keys if k in set(datasets)]
    out: list[BuildResult] = []
    with pg.connect() as con:
        for k in keys:
            out.append(build_dataset(k, con))
    return out
