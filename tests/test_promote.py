"""`dab promote`'s decide(): most answers passed wins, a tie keeps the incumbent, and a tie
between two challengers goes to whichever's run started first. No model, no Postgres."""

from __future__ import annotations

from dab_bench.eval.promote import Candidate, decide


def test_most_passed_wins() -> None:
    cands = [
        Candidate("v0", "r0", 27, 54, 54, started_at="2026-09-01T00:00:00+00:00"),
        Candidate("v1_sql", "r1", 24, 54, 54, started_at="2026-09-02T00:00:00+00:00"),
        Candidate("v2_sql", "r2", 30, 54, 54, started_at="2026-09-03T00:00:00+00:00"),
    ]
    winner, reason = decide(cands, incumbent="v0")
    assert winner == "v2_sql"
    assert "v2_sql" in reason


def test_tie_with_incumbent_keeps_incumbent() -> None:
    cands = [
        Candidate("v0", "r0", 30, 54, 54, started_at="2026-09-01T00:00:00+00:00"),
        Candidate("v2_sql", "r2", 30, 54, 54, started_at="2026-09-03T00:00:00+00:00"),
    ]
    winner, reason = decide(cands, incumbent="v0")
    assert winner == "v0"
    assert "keeps the title" in reason


def test_tie_between_two_challengers_goes_to_whichever_run_started_first() -> None:
    cands = [
        Candidate("v0", "r0", 20, 54, 54, started_at="2026-09-01T00:00:00+00:00"),
        Candidate("v10_sql", "r10", 30, 54, 54, started_at="2026-09-05T00:00:00+00:00"),
        Candidate("v2_sql", "r2", 30, 54, 54, started_at="2026-09-03T00:00:00+00:00"),
    ]
    # lexicographic sort would put "v10_sql" before "v2_sql"; the older run must win instead
    winner, reason = decide(cands, incumbent="v0")
    assert winner == "v2_sql"
    assert "older run" in reason


# ── D36 (plan s08): the statement decides, the answer breaks a tie ─────────────


def _c(v: str, passed: int, sql: int | None, started: str) -> Candidate:
    card = {"sql": {"passed": sql, "n": 49}} if sql is not None else {"sql": {"passed": 0, "n": 0}}
    return Candidate(v, f"r_{v}", passed, 54, 54, scorecard=card, started_at=started)


def test_the_most_sql_passed_wins_over_more_answers() -> None:
    cands = [
        _c("v0", 27, None, "2026-09-01"),  # no statement to score: counts as no SQL passed
        _c("v2_sql", 32, 18, "2026-09-03"),
        _c("v3_sql", 30, 21, "2026-09-05"),
    ]
    winner, reason = decide(cands, incumbent="v2_sql")
    assert winner == "v3_sql" and "the most SQL passed" in reason
    assert "v0 no SQL" in reason and "v3_sql SQL 21/49 · answers 30/54" in reason


def test_answers_break_a_tie_on_sql() -> None:
    cands = [_c("v2_sql", 30, 20, "2026-09-03"), _c("v3_sql", 33, 20, "2026-09-05")]
    winner, reason = decide(cands, incumbent="v2_sql")
    assert winner == "v3_sql" and "answers break the tie on SQL" in reason


def test_a_tie_on_both_keeps_the_incumbent_then_the_older_run_wins() -> None:
    cands = [_c("v2_sql", 30, 20, "2026-09-03"), _c("v3_sql", 30, 20, "2026-09-05")]
    assert decide(cands, incumbent="v2_sql")[0] == "v2_sql"
    cands = [_c("v0", 20, None, "2026-09-01"), *cands]
    winner, reason = decide(cands, incumbent="v0")
    assert winner == "v2_sql" and "older run" in reason
