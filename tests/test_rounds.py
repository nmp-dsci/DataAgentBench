"""Optimisation rounds read as a baseline against a candidate, per question (eval/rounds.py)."""

from __future__ import annotations

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
