"""The SQL ledger (plan s08, eval/ledger.py): what the reader writes is checked and redacted, and
a run's ledger is read into its scorecard only where it describes the same golden and the same
statement. No model, no Postgres."""

from __future__ import annotations

from typing import Any

from dab_bench.eval import ledger as lg
from dab_bench.eval import scorecard as sc

Q = "Which five repositories written in Swift have the most stars and forks together?"
GOLD = "repo,lang\nswift-org/swift,Swift\nvapor/vapor,Swift"


def test_lines_are_seven_one_per_component_and_a_missing_one_reads_none() -> None:
    got = lg.clean_lines({"keys": "  strip the prefix  ", "parse": "", "extra": "dropped"})
    assert list(got) == list(lg.COMPONENTS)
    assert got["keys"] == "strip the prefix" and got["parse"] == "none" and "extra" not in got
    assert len(lg.clean_lines({"sources": "x" * 900})["sources"]) == 400


def test_verdicts_default_to_same_and_the_break_must_differ() -> None:
    v = lg.clean_verdicts({"keys": "differs", "parse": "DIFFERS", "rank": "maybe"})
    assert v["keys"] == "differs" and v["parse"] == "differs" and v["rank"] == "same"
    assert lg.first_break(v, "parse") == "parse"  # the reader's pick, when it does differ
    assert lg.first_break(v, "rank") == "keys"  # not a differing step: the first that is
    assert lg.first_break(v, "none") == "keys"
    assert lg.first_break(lg.clean_verdicts({}), "none") is None


def test_a_gold_value_written_literally_is_redacted() -> None:
    lines = lg.clean_lines(
        {"rank": "keeps vapor/vapor first, then ties by name", "sources": "the Swift repos"}
    )
    out, hits = lg.redact(lines, [(Q, GOLD)])
    assert "vapor/vapor" not in out["rank"] and "…" in out["rank"] and hits == ["vapor/vapor"]
    assert out["sources"] == "the Swift repos"  # the question names Swift: not a leak


def _row(**kw: Any) -> dict[str, Any]:
    base = {
        "query_id": "yelp/2",
        "trial": 1,
        "answer": False,
        "sql": False,
        "decision": True,
        "golden_id": 7,
        "category": "join differs",
        "detail": "",
    }
    return base | kw


def _ledger(sql: str, golden_id: int = 7) -> dict[str, Any]:
    verdicts = lg.clean_verdicts({"parse": "differs", "rank": "differs"})
    return {
        "goldens": {
            "yelp/2": {
                "golden_id": golden_id,
                "lines": lg.clean_lines({"parse": "three phrasings"}),
            }
        },
        "questions": {
            "yelp/2": {
                "golden_id": golden_id,
                "agent_sql_sha": lg.sql_sha(sql),
                "agent": lg.clean_lines({"parse": "one phrasing"}),
                "verdicts": verdicts,
                "breaks_at": "parse",
                "why": "reads one of three phrasings",
            }
        },
    }


def test_attach_categorises_a_failed_trial_by_where_it_breaks() -> None:
    sql = "select 1\n from t"
    rows = [_row()]
    lg.attach(rows, _ledger("select 1 from t"), {"yelp/2": sql})  # whitespace does not matter
    assert rows[0]["category"] == "breaks at parse" and rows[0]["breaks_at"] == "parse"
    assert rows[0]["ledger"]["golden"]["parse"] == "three phrasings"
    assert rows[0]["ledger"]["agent"]["parse"] == "one phrasing"
    assert "breaks at parse" in sc.CATEGORIES


def test_attach_ignores_a_ledger_of_another_statement_or_golden() -> None:
    rows = [_row()]
    lg.attach(rows, _ledger("select 2 from t"), {"yelp/2": "select 1 from t"})
    assert rows[0]["category"] == "join differs"  # the statement changed: no comparison
    assert "agent" not in rows[0]["ledger"] and rows[0]["ledger"]["golden"]
    rows = [_row()]
    lg.attach(rows, _ledger("select 1 from t", golden_id=6), {"yelp/2": "select 1 from t"})
    assert "ledger" not in rows[0]  # a new golden was saved since: its lines are not these


def test_attach_keeps_categories_that_are_not_about_the_statement() -> None:
    rows = [_row(category="SQL error"), _row(query_id="yelp/3", sql=True, category="solved")]
    lg.attach(rows, _ledger("select 1 from t"), {"yelp/2": "select 1 from t"})
    assert rows[0]["category"] == "SQL error"
    assert rows[1]["category"] == "solved" and "ledger" not in rows[1]


def test_only_a_statement_that_ran_and_failed_is_compared() -> None:
    assert lg.needs_comparison(_row(), "select 1")
    assert not lg.needs_comparison(_row(sql=True), "select 1")
    assert not lg.needs_comparison(_row(category="no SQL"), None)
    assert not lg.needs_comparison(_row(golden_id=None), "select 1")


def test_the_comparison_message_names_every_step_and_both_statements() -> None:
    msg = lg.compare_message(
        Q,
        lg.clean_lines({"keys": "exact key"}),
        "select a from golden_t",
        "select a from agent_t",
        "returns 1 row(s); the golden returns 2",
        [{"op": "del", "text": "x"}, {"op": "ins", "text": "y"}],
    )
    for c in lg.COMPONENTS:
        assert f"- {c}:" in msg
    assert "golden_t" in msg and "agent_t" in msg and "- x" in msg and "+ y" in msg


def test_a_golden_is_reused_only_from_the_same_reader_model(monkeypatch: Any) -> None:
    from contextlib import contextmanager

    from dab_bench.data import pg

    rows = [(1, {"sources": "a"}, "claude-sonnet-5"), (2, {"sources": "b"}, "claude-opus-5-5")]

    class Con:
        def execute(self, *_: Any) -> Any:
            return self

        def fetchall(self) -> list[Any]:
            return rows

    @contextmanager
    def connect() -> Any:
        yield Con()

    monkeypatch.setattr(pg, "connect", connect)
    monkeypatch.setattr(lg, "ensure_table", lambda: None)
    assert set(lg.cached([1, 2])) == {1, 2}  # no model: any reader's lines
    assert set(lg.cached([1, 2], "claude-opus-5-5")) == {2}  # another model reads it again
