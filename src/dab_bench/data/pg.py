"""Postgres helpers: connections, the schema and roles, and what is loaded.

`roles.sql` is applied as the server's superuser once (`dab data init`); every
other command connects as `dab_owner` (load, check, context build) or, for the
agent's tools, as the read-only `dab_agent`. Nothing here reads `os.environ`;
the URLs come from `config.settings()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg

from dab_bench.config import INFRA_DIR, PG_SCHEMA, settings

ROLES_SQL = INFRA_DIR / "roles.sql"


def connect(url: str | None = None, autocommit: bool = True) -> psycopg.Connection[Any]:
    return psycopg.connect(url or settings().database_url, autocommit=autocommit)


def connect_agent() -> psycopg.Connection[Any]:
    return psycopg.connect(settings().agent_database_url, autocommit=True)


def init_schema() -> None:
    """Apply `infra/roles.sql` as the superuser. Idempotent."""
    with psycopg.connect(settings().pg_superuser_url, autocommit=True) as con:
        con.execute(ROLES_SQL.read_text())  # type: ignore[arg-type,unused-ignore]


def reachable(url: str | None = None) -> bool:
    try:
        with connect(url) as con:
            con.execute("select 1")
        return True
    except Exception:  # noqa: BLE001 - the caller prints the one-line remedy
        return False


@dataclass(frozen=True)
class TableInfo:
    name: str
    rows: int | None


def list_tables(con: psycopg.Connection[Any], prefix: str | None = None) -> list[str]:
    rows = con.execute(
        "select table_name from information_schema.tables "
        "where table_schema = %s and table_type = 'BASE TABLE' order by table_name",
        (PG_SCHEMA,),
    ).fetchall()
    names = [r[0] for r in rows]
    return [n for n in names if n.startswith(prefix)] if prefix else names


def count_rows(con: psycopg.Connection[Any], table: str) -> int:
    row = con.execute(f'select count(*) from {PG_SCHEMA}."{table}"').fetchone()
    return int(row[0]) if row else 0


def drop_table(con: psycopg.Connection[Any], table: str) -> None:
    con.execute(f'drop table if exists {PG_SCHEMA}."{table}" cascade')


def columns(con: psycopg.Connection[Any], table: str) -> list[tuple[str, str]]:
    rows = con.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_schema = %s and table_name = %s order by ordinal_position",
        (PG_SCHEMA, table),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]
