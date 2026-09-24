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
        (["title"], [], "The Rundown", "differs"),  # no rows is never the gold "reordered"
        (["name", "v"], [], "Name,V\nx,2.6.2", "differs"),
    ],
)
def test_the_result_is_matched_against_the_gold_itself(
    columns: list[str], rows: list[list[object]], gold: str, match: str
) -> None:
    assert golden.match_gold(columns, rows, gold)["match"] == match


def _ops(diff: list[dict[str, object]]) -> list[tuple[object, ...]]:
    return [(d["op"], d["gold"], d["result"], tuple(d.get("changed", ()))) for d in diff]  # type: ignore[arg-type]


def test_the_diff_shows_gold_lines_removed_and_result_lines_added() -> None:
    gold = "\ufeffName,Version\na,1.0\nb,2.0\nc,3.0"
    # b's version differs; c is missing; d is extra; the header differs only in case
    diff = golden.gold_diff(["name", "version"], [["a", "1.0"], ["b", "2.1"], ["d", "4.0"]], gold)
    assert _ops(diff) == [
        ("eq", 1, 1, ()),
        ("eq", 2, 2, ()),
        ("del", 3, None, (1,)),
        ("del", 4, None, (0, 1)),
        ("add", None, 3, (1,)),
        ("add", None, 4, (0, 1)),
    ]
    assert [d["text"] for d in diff if d["op"] == "add"] == ["b,2.1", "d,4.0"]


def test_the_diff_ignores_what_the_gold_match_ignores() -> None:
    # float noise in the last digit, and a gold with no header: nothing to show but equal lines
    diff = golden.gold_diff(["s", "r"], [["PA", 3.6993957703927493]], "PA,3.699395770392749")
    assert _ops(diff) == [("eq", 1, 1, ())]


def test_a_missing_row_is_only_removed() -> None:
    diff = golden.gold_diff(["t"], [["a"], ["c"]], "a\nb\nc")
    assert _ops(diff) == [("eq", 1, 1, ()), ("del", 2, None, ()), ("eq", 3, 2, ())]


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


@live
def test_an_evidence_golden_is_run_but_not_judged() -> None:
    """D23: a judgment question's golden returns the evidence; the answer is recorded beside it."""
    client = TestClient(create_app())
    body = {"sql": "select 1 as evidence", "kind": "evidence", "expected_answer": "Authority"}
    saved = client.post("/api/golden/crmarenapro/1", json=body).json()
    gid = saved["saved"]["id"]
    try:
        assert saved["kind"] == "evidence" and saved["verdict"]["passed"] is None
        assert saved["verdict"]["reason"] == golden.EVIDENCE_REASON
        assert saved["gold_match"]["match"] == ""
        cur = client.get("/api/golden/crmarenapro/1").json()["current"]
        assert cur["kind"] == "evidence" and cur["expected_answer"] == "Authority"
        row = next(
            q for q in client.get("/api/golden").json()["queries"] if q["id"] == "crmarenapro/1"
        )
        assert row["golden"]["kind"] == "evidence"
    finally:
        with psycopg.connect(settings().database_url, autocommit=True) as con:
            con.execute(f"delete from {PG_META_SCHEMA}.golden_sql where id = %s", (gid,))


@live
def test_a_proposal_is_checked_shown_and_not_a_golden() -> None:
    from dab_bench.data.index import load

    ix = load()
    q = ix.query_by_id["yelp/1"]
    out, ex = golden.attempt(q, ix.dataset_by_key["yelp"]["folder"], YELP_1)
    pid = golden.propose("yelp/1", YELP_1, out, ex, replaces="nothing", note="test")["id"]
    try:
        client = TestClient(create_app())
        one = client.get("/api/golden/yelp/1").json()
        assert one["proposal"]["id"] == pid and one["proposal"]["passed"] is True
        assert one["proposal"]["gold_match"] == "exact" and one["proposal"]["author"] == "claude"
        listing = client.get("/api/golden").json()
        row = next(r for r in listing["queries"] if r["id"] == "yelp/1")
        assert row["proposal"]["id"] == pid
        # a proposal is not a golden: nothing was saved on its behalf
        assert all(h["source"] != f"proposal #{pid}" for h in one["history"])
    finally:
        with psycopg.connect(settings().database_url, autocommit=True) as con:
            con.execute(f"delete from {PG_META_SCHEMA}.golden_proposal where id = %s", (pid,))


@live
def test_the_agent_role_cannot_read_the_proposals() -> None:
    golden.ensure_table()
    with (
        psycopg.connect(settings().agent_database_url, autocommit=True) as con,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        con.execute(f"select * from {PG_META_SCHEMA}.golden_proposal")


def test_a_golden_saved_from_a_golden_is_traced_to_where_its_sql_began() -> None:
    sources = {1: "proposal #7", 2: "golden #1", 3: "golden #2", 4: "", 5: "golden #9"}
    assert golden.origin("golden #3", sources) == "proposal #7"
    assert golden.origin("golden #4", sources) == ""  # by hand
    assert golden.origin("golden #5", sources) == "golden #9"  # an unknown id stays as recorded
    assert (
        golden.origin("r1 · deps_dev_v1/1/t1 · query_db #2", sources)
        == "r1 · deps_dev_v1/1/t1 · query_db #2"
    )


def test_a_single_value_keeps_the_header_the_gold_file_writes() -> None:
    # github_repos/2: the validator slides a 21-character window, so the bare 18-character
    # answer can never pass; the gold file writes `repo_name` above it, and so does the render
    gold = "repo_name\nSwiftAndroid/swift"
    assert golden.render_like_gold(["repo_name"], [["SwiftAndroid/swift"]], gold) == gold
    assert golden.render_like_gold(["n"], [["SwiftAndroid/swift"]], gold) == "SwiftAndroid/swift"
    assert golden.render_like_gold(["avg"], [[3.5]], "3.5") == "3.5"  # a gold with no header
    assert golden.render_like_gold(["a", "b"], [["x", 1]], "a,b\nx,1") == "a,b\nx,1"
