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
