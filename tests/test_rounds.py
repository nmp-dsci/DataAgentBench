"""Optimisation rounds read as a baseline against a candidate, per question (eval/rounds.py)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dab_bench.eval.rounds import change, summarise_changes


def _q(qid: str, before: bool, after: bool, split: str, cat_b: str, cat_a: str) -> dict[str, Any]:
    return {
        "query_id": qid,
        "dataset": qid.split("/")[0],
        "split": split,
        "before": {"answer": before, "category": cat_b},
        "after": {"answer": after, "category": cat_a},
        "change": change(before, after),
    }


def test_change_names_the_four_outcomes_and_an_unscored_side() -> None:
    assert change(False, True) == "improved"
    assert change(True, False) == "regressed"
    assert change(True, True) == "held"
    assert change(False, False) == "still failing"
    assert change(None, True) == "not scored"


def test_summary_counts_per_split_per_dataset_and_category_moves() -> None:
    rows = [
        _q("yelp/1", False, True, "train", "join differs", "solved"),
        _q("yelp/2", True, False, "heldout", "solved", "parse differs"),
        _q("patents/1", False, False, "train", "no SQL", "join differs"),
        _q("patents/2", True, True, "train", "solved", "solved"),
    ]
    s = summarise_changes(rows)
    assert s["all"]["before"] == 2 and s["all"]["after"] == 2
    assert (s["all"]["improved"], s["all"]["regressed"], s["all"]["held"]) == (1, 1, 1)
    assert s["by_split"]["train"]["before"] == 1 and s["by_split"]["train"]["after"] == 2
    assert s["by_split"]["heldout"]["regressed"] == 1
    assert s["by_dataset"]["patents"]["n"] == 2 and s["by_dataset"]["patents"]["held"] == 1
    moves = {(m["from"], m["to"]): m["n"] for m in s["category_moves"]}
    assert moves[("join differs", "solved")] == 1 and moves[("solved", "solved")] == 1


def test_sql_is_tallied_beside_the_answer_over_the_goldened_questions() -> None:
    rows = [
        _q("yelp/1", False, True, "train", "breaks at keys", "solved"),
        _q("yelp/2", True, True, "heldout", "solved", "solved"),
        _q("agnews/1", True, True, "no golden", "no golden", "no golden"),
    ]
    for r, (b, a) in zip(rows, [(False, True), (True, True), (None, None)], strict=True):
        r["before"]["sql"], r["after"]["sql"] = b, a
        r["sql_change"] = change(b, a)
    s = summarise_changes(rows)["all"]["sql"]
    assert (s["n"], s["before"], s["after"], s["improved"], s["held"]) == (2, 1, 2, 1, 1)


def test_a_round_one_record_reads_as_refusals_then_one_accepted_write() -> None:
    from dab_bench.eval.rounds import attempts, session_kind

    old = {
        "scope": "yelp",
        "notes": "x" * 1500,
        "refusals": [
            {"problems": ["1,742 characters; the limit is 1,500"], "notes_chars": 1742},
            {"problems": ["gold values written literally: a"], "notes_chars": 1400},
        ],
    }
    got = attempts(old)
    assert [a["ok"] for a in got] == [False, False, True] and got[-1]["chars"] == 1500
    assert session_kind(old) == "dataset" and session_kind({"scope": "system.md"}) == "system"
    new = {
        "scope": "playbook:keys",
        "kind": "component",
        "attempts": [{"ok": True, "chars": 9, "problems": []}],
    }
    assert attempts(new) == new["attempts"] and session_kind(new) == "component"


# ── how each version was made, under the versions figure ──────────────────────


def test_a_version_is_a_round_a_model_change_a_build_change_or_the_base(tmp_path: Path) -> None:
    from dab_bench.agent.versions import AgentConfig
    from dab_bench.eval.rounds import version_change

    haiku = AgentConfig(model="haiku", tools=["mcp__dab__query_db", "mcp__dab__list_db"])
    sql = AgentConfig(model="haiku", tools=["mcp__dab__query_db", "mcp__dab__submit_answer"])
    sonnet = AgentConfig(model="sonnet", tools=sql.tools)
    strict = {"guards": dict.fromkeys(("g1_review", "g2_audit", "g3_breadth", "g4_routing"), True)}
    assert version_change(haiku, None, None, None) == {"kind": "base", "detail": "the first build"}
    assert version_change(sql, haiku, None, None) == {"kind": "build", "detail": "SQL answer"}
    assert version_change(sonnet, sql, None, None) == {"kind": "model", "detail": "haiku → sonnet"}
    assert version_change(sonnet, sql, {"guards": {}}, 2) == {"kind": "round", "detail": "round 2"}
    got = version_change(sonnet, sonnet, strict, 5)
    assert got == {"kind": "round", "detail": "round 5 · G1–G4"}


def test_the_note_is_the_versions_own_line_atop_its_agent_yaml(tmp_path: Path) -> None:
    from dab_bench.eval.rounds import header_note

    p = tmp_path / "agent.yaml"
    p.write_text(
        "# v5_sql: v4_sql's prompt files on opus (was sonnet); a model switch, not a round\n"
        "# v4_sql: v3_sql's prompt files on sonnet (was haiku); a model switch, not a round\n"
        "model: opus\n"
    )
    assert (
        header_note(p)
        == "v5_sql: v4_sql's prompt files on opus (was sonnet); a model switch, not a round"
    )
    p.write_text(
        "# v1_sql — the SQL-answer challenger. Frozen across a comparison: only\n# system.md moves.\nmodel: haiku\n"
    )
    assert (
        header_note(p)
        == "v1_sql — the SQL-answer challenger. Frozen across a comparison: only system.md moves."
    )
    assert header_note(tmp_path / "missing.yaml") == ""
