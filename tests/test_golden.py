"""Golden SQL: rendered like the gold, run as the agent's role, judged by the validator.

The rendering tests run everywhere. The live ones need the central Postgres
(`DAB_TEST_PG=1`): a real golden for yelp/1 passes through the API, a save is
appended and read back (then removed), and `dab_agent` cannot read the table.
"""

import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from dab_bench.config import PG_META_SCHEMA, settings
from dab_bench.eval import golden
from dab_bench.serving.app import create_app

live = pytest.mark.skipif(
    not os.environ.get("DAB_TEST_PG"), reason="needs the central Postgres (DAB_TEST_PG=1)"
)

YELP_1 = """select avg(r.rating) from yelp_review r
join yelp_business b
  on replace(r.business_ref, 'businessref_', '') = replace(b.business_id, 'businessid_', '')
where b.description ilike '%Indianapolis, IN%'"""


def test_one_value_renders_alone() -> None:
    assert golden.render(["avg"], [[3.547008547008547]]) == "3.547008547008547"
    assert golden.render(["n"], [[42.0]]) == "42"


def test_a_table_renders_like_the_gold_files() -> None:
    text = golden.render(["name", "n"], [["a", 1], ["b", None]])
    assert text == "name,n\na,1\nb,NULL"
    assert golden.render(["x"], []) == ""


@pytest.mark.parametrize(
    ("columns", "rows", "gold", "match"),
    [
        (["avg"], [[3.547008547008547]], "3.547008547008547", "exact"),
        (["avg"], [[2.7135713051934523]], "2.713571305193452", "exact"),  # last-digit noise
        (["name", "v"], [["x", "2.6.2"]], "\ufeffName,V\nx,2.6.2", "exact"),  # BOM, header case
        (["n", "v"], [["x", "2.6.2"]], "Name,Version\nx,2.6.2", "exact_values"),
        (["t"], [["b"], ["a"]], "a\nb", "reordered"),
        (["state", "r"], [["PA", 3.699395770392749]], "PA,3.699395770392749", "exact"),  # no header
        (["avg"], [[3.2]], "3.547008547008547", "differs"),
    ],
)
def test_the_result_is_matched_against_the_gold_itself(
    columns: list[str], rows: list[list[object]], gold: str, match: str
) -> None:
    assert golden.match_gold(columns, rows, gold)["match"] == match


def test_writes_are_refused_before_the_database() -> None:
    for sql in ("drop table yelp_review", "  DELETE FROM x", "set role dab_owner"):
        assert golden.execute(sql).error


@live
def test_a_golden_runs_as_the_agent_and_passes_its_validator() -> None:
    client = TestClient(create_app())
    r = client.post("/api/golden/yelp/1/run", json={"sql": YELP_1}).json()
    assert r["answer_text"] == "3.547008547008547"
    assert r["verdict"]["passed"] is True and r["gold_match"]["match"] == "exact"

    wrong = client.post("/api/golden/yelp/1/run", json={"sql": "select 3.2"}).json()
    assert wrong["verdict"]["passed"] is False

    bad = client.post("/api/golden/yelp/1/run", json={"sql": "select nope from yelp_review"})
    assert bad.json()["verdict"]["passed"] is None and "nope" in bad.json()["verdict"]["reason"]
    # the agent's role cannot see the goldens or the questions from inside a golden
    peek = client.post(
        "/api/golden/yelp/1/run", json={"sql": f"select * from {PG_META_SCHEMA}.golden_sql"}
    ).json()
    assert "permission denied" in peek["verdict"]["reason"]


@live
def test_a_save_is_appended_and_becomes_current() -> None:
    client = TestClient(create_app())
    src = "run 20260921T064521Z_v0_all_haiku · yelp/1/t1 · query_db #2"
    saved = client.post(
        "/api/golden/yelp/1", json={"sql": YELP_1, "note": "test", "source": src}
    ).json()
    gid = saved["saved"]["id"]
    try:
        one = client.get("/api/golden/yelp/1").json()
        assert one["current"]["id"] == gid and one["current"]["passed"] is True
        assert one["current"]["gold_match"] == "exact"
        # a golden seeded from a run's trial says where it started
        assert one["current"]["source"] == src and one["history"][0]["source"] == src
        listing = client.get("/api/golden").json()
        row = next(q for q in listing["queries"] if q["id"] == "yelp/1")
        assert row["golden"]["passed"] is True and listing["n"] == 54
    finally:
        with psycopg.connect(settings().database_url, autocommit=True) as con:
            con.execute(f"delete from {PG_META_SCHEMA}.golden_sql where id = %s", (gid,))


@live
def test_the_agent_role_cannot_read_the_goldens() -> None:
    golden.ensure_table()
    with (
        psycopg.connect(settings().agent_database_url, autocommit=True) as con,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        con.execute(f"select * from {PG_META_SCHEMA}.golden_sql")
