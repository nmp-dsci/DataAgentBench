"""The question set's copy in Postgres: derived from the index, and closed to the agent.

The copy holds every gold answer, so the test that matters is the negative one — the
read-only role the agent's `query_db` uses cannot reach it. Needs the live server
(`DAB_TEST_PG=1`); the shape test below runs everywhere.
"""

from __future__ import annotations

import json
import os

import pytest

from dab_bench.config import PG_META_SCHEMA, PG_SCHEMA, QUERIES_PATH
from dab_bench.data.meta import COLUMNS, QUESTIONS_TABLE, _rows


def test_the_copy_is_the_index_row_for_row() -> None:
    src = json.loads(QUERIES_PATH.read_text())
    rows = _rows("deadbeef", __import__("datetime").datetime.now(__import__("datetime").UTC))
    assert len(rows) == len(src)
    by_id = {r[0]: r for r in rows}
    for q in src:
        r = by_id[q["id"]]
        assert r[COLUMNS.index("question")] == q["question"]
        assert r[COLUMNS.index("gold_text")] == q["gold_text"]
        assert r[COLUMNS.index("upstream_commit")] == "deadbeef"


def test_the_copy_lives_outside_the_schema_the_agent_reads() -> None:
    assert PG_META_SCHEMA != PG_SCHEMA  # a gold table in PG_SCHEMA would be granted to dab_agent


@pytest.mark.skipif(
    not os.environ.get("DAB_TEST_PG"), reason="needs the central Postgres (DAB_TEST_PG=1)"
)
def test_the_agent_role_cannot_read_the_questions() -> None:
    import psycopg

    from dab_bench.data import pg
    from dab_bench.data.meta import load_questions

    r = load_questions()
    assert r.rows == len(json.loads(QUERIES_PATH.read_text()))
    with pg.connect() as owner:
        n = owner.execute(f"select count(*) from {PG_META_SCHEMA}.{QUESTIONS_TABLE}").fetchone()
        assert n and n[0] == r.rows
    agent = pg.connect_agent()
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            agent.execute(f"select * from {PG_META_SCHEMA}.{QUESTIONS_TABLE} limit 1").fetchone()
        # …and it is not on the agent's search_path either, so a bare name misses too.
        with pytest.raises(psycopg.errors.UndefinedTable):
            agent.execute(f"select * from {QUESTIONS_TABLE} limit 1").fetchone()
    finally:
        agent.close()
