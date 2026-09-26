"""`dab promote`'s decide(): the leak gate, then the highest Pass@1, answers and SQL break a
tie, a tie on all keeps the incumbent, and a tie between two challengers goes to whichever's
run started first (D46). No model, no Postgres."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dab_bench.eval import outcome
from dab_bench.eval.promote import Candidate, decide, leak_gate


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


# ── D46 (s14): the leak gate, then the leaderboard's number ─────────────────


def _c(
    v: str, p1: float | None, passed: int, sql: int | None, started: str, gate: str = ""
) -> Candidate:
    card = {"sql": {"passed": sql, "n": 49}} if sql is not None else {"sql": {"passed": 0, "n": 0}}
    return Candidate(
        v, f"r_{v}", passed, 54, 54, scorecard=card, started_at=started, pass_at_1=p1, gate=gate
    )


def test_the_highest_pass_at_1_wins_over_more_sql() -> None:
    cands = [
        _c("v0", 0.44, 27, None, "2026-09-01"),  # no statement to score: counts as no SQL
        _c("v6_sql", 0.891, 46, 33, "2026-09-25T01"),
        _c("v8_sql", 0.904, 48, 31, "2026-09-25T06"),
    ]
    winner, reason = decide(cands, incumbent="v6_sql")
    assert winner == "v8_sql" and "the highest Pass@1" in reason
    assert "v0 Pass@1 0.440 · answers 27/54 · no SQL" in reason
    assert "v8_sql Pass@1 0.904 · answers 48/54 · SQL 31/49" in reason


def test_answers_then_sql_break_a_tie_on_pass_at_1() -> None:
    cands = [_c("v2_sql", 0.8, 44, 30, "2026-09-03"), _c("v3_sql", 0.8, 45, 20, "2026-09-05")]
    winner, reason = decide(cands, incumbent="v2_sql")
    assert winner == "v3_sql" and "answers break the tie on Pass@1" in reason
    cands = [_c("v2_sql", 0.8, 44, 30, "2026-09-03"), _c("v3_sql", 0.8, 44, 31, "2026-09-05")]
    winner, reason = decide(cands, incumbent="v2_sql")
    assert winner == "v3_sql" and "SQL breaks the tie on Pass@1 and answers" in reason


def test_a_tie_on_all_three_keeps_the_incumbent_then_the_older_run_wins() -> None:
    cands = [_c("v2_sql", 0.8, 44, 30, "2026-09-03"), _c("v3_sql", 0.8, 44, 30, "2026-09-05")]
    assert decide(cands, incumbent="v2_sql")[0] == "v2_sql"
    cands = [_c("v0", 0.4, 20, None, "2026-09-01"), *cands]
    winner, reason = decide(cands, incumbent="v0")
    assert winner == "v2_sql" and "older run" in reason


def test_a_challenger_the_leak_gate_bars_cannot_win_but_the_incumbent_stands() -> None:
    gate = "its round ran without guards G1–G4"
    cands = [
        _c("v6_sql", 0.891, 46, 33, "2026-09-25T01", gate=gate),  # the incumbent: stands
        _c("v9_sql", 0.95, 50, 40, "2026-09-26", gate=gate),
    ]
    winner, reason = decide(cands, incumbent="v6_sql")
    assert winner == "v6_sql" and "barred by the leak gate: v9_sql" in reason
    assert "v9_sql Pass@1" not in reason  # a barred challenger is not weighed


def _version(root: Path, name: str, notes: str = "", **yaml_keys: str) -> Path:
    d = root / name
    (d / "datasets").mkdir(parents=True)
    (d / "system.md").write_text("Answer with one SQL statement.")
    (d / "datasets" / "yelp.md").write_text(notes or "Cities are stored in title case.")
    (d / "agent.yaml").write_text("".join(f"{k}: {v}\n" for k, v in yaml_keys.items()))
    return d


def _round(d: Path, strict: bool) -> None:
    guards = dict.fromkeys(("literal", "g1_review", "g2_audit", "g3_breadth", "g4_routing"), strict)
    guards["literal"] = True
    (d / "optimise.json").write_text(json.dumps({"guards": guards}))


GOLDS = [("Which city has the most reviews?", "city\nPhiladelphia")]


def test_the_leak_gate_reads_the_round_that_made_the_version(tmp_path: Path) -> None:
    _version(tmp_path, "v1")  # a base version: no round, no source
    assert leak_gate("v1", tmp_path, GOLDS) == ""
    _round(_version(tmp_path, "v2", challenger_of="v1"), strict=False)
    assert "without guards G1–G4" in leak_gate("v2", tmp_path, GOLDS)
    _version(tmp_path, "v3", measured_against="v2")  # a model switch: v2's text
    assert "its text is v2's" in leak_gate("v3", tmp_path, GOLDS)
    _round(_version(tmp_path, "v4", challenger_of="v3"), strict=True)
    assert leak_gate("v4", tmp_path, GOLDS) == ""


def test_the_leak_gate_bars_a_gold_value_anywhere_in_the_prompt(tmp_path: Path) -> None:
    d = _version(tmp_path, "v4", notes="The busiest city is Philadelphia.", challenger_of="v3")
    _round(d, strict=True)
    got = leak_gate("v4", tmp_path, GOLDS)
    assert got == "G2: 1 gold value(s) in notes:yelp" and "Philadelphia" not in got


def test_a_barred_challenger_did_not_stand_for_its_outcome() -> None:
    p = {
        "incumbent": "v6_sql",
        "winner": "v6_sql",
        "candidates": [
            {"version": "v6_sql", "run_id": "r6", "why_not": "", "gate": "old round"},
            {"version": "v5_sql", "run_id": "r5", "why_not": "", "gate": "old round"},
            {"version": "v8_sql", "run_id": "r8", "why_not": "", "gate": ""},
        ],
    }
    assert outcome._stood(p, "v6_sql") and outcome._stood(p, "v8_sql")
    assert outcome._stood(p, "v5_sql") is None


@pytest.mark.parametrize("name", ["v7_sql", "v8_sql"])
def test_the_strict_rounds_pass_the_leak_gate(name: str) -> None:
    assert leak_gate(name) == ""
