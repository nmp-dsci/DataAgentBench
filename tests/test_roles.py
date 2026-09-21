"""The agent role can read the benchmark schema and nothing else. Needs the live Postgres.

Skipped unless DAB_TEST_PG=1 (CI has no server); `make db-up && DAB_TEST_PG=1 uv run pytest tests/test_roles.py`.
"""

from __future__ import annotations

import os

import psycopg
import pytest

from dab_bench.config import PG_SCHEMA, settings
from dab_bench.data import pg

pytestmark = pytest.mark.skipif(
    os.environ.get("DAB_TEST_PG") != "1", reason="needs DAB_TEST_PG=1 and a live Postgres"
)


def test_agent_role_reads_the_schema_and_cannot_write_or_leave_it() -> None:
    with pg.connect_agent() as con:
        # search_path is the schema: unqualified names resolve
        assert con.execute("show search_path").fetchone()[0] == PG_SCHEMA  # type: ignore[index]
        assert con.execute("show statement_timeout").fetchone()[0] == "1min"  # type: ignore[index]
        n = con.execute(
            "select count(*) from information_schema.tables where table_schema = %s", (PG_SCHEMA,)
        ).fetchone()
        assert n and n[0] > 0
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            con.execute(f'create table {PG_SCHEMA}."zz_should_fail" (x int)')
        # read-only wins before the privilege check on any schema
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            con.execute("create table public.zz_should_fail (x int)")
        # and even a read-write transaction has no privilege outside the schema
        con.execute("set default_transaction_read_only = off")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            con.execute("create table public.zz_should_fail (x int)")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            con.execute(f'create table {PG_SCHEMA}."zz_should_fail" (x int)')


def test_agent_role_statement_timeout_is_enforced() -> None:
    with pg.connect_agent() as con, pytest.raises(psycopg.errors.QueryCanceled):
        con.execute("select pg_sleep(61)")


def test_owner_url_and_agent_url_differ() -> None:
    s = settings()
    assert s.database_url != s.agent_database_url
