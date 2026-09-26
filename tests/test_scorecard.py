"""The scorecard (answer / SQL / decision + a category), the optimiser's split, its leak guards
and what one optimiser session is shown. No model, no Postgres: goldens are built in memory."""

from __future__ import annotations

import json
from typing import Any

import pytest

from dab_bench.agent.optimise import briefing
from dab_bench.agent.versions import load_version
from dab_bench.config import SPLITS_DIR
from dab_bench.eval import scorecard as sc
from dab_bench.eval.guards import Guard, gold_cells, golden_fragments, question_runs

# ── comparing results ─────────────────────────────────────────────────────────


def test_same_rows_in_any_order_any_column_order_and_names_pass() -> None:
    got = sc.compare_results(
        ["repo", "stars"],
        [["a/b", 10], ["c/d", 7]],
        ["Stars", "Name", "extra"],
        [[7.0, "C/D", 1], [10, "a/b", 2]],
        "answer",
    )
    assert got["pass"] and "extra column" in got["detail"]


@pytest.mark.parametrize(
    ("rows", "says"),
    [
        ([["a/b", 10]], "returns 1 row(s); the golden returns 2"),
        ([["a/b", 10], ["c/d", 8]], "the values differ"),
        ([], "no rows"),
    ],
)
def test_a_different_result_fails(rows: list[list[Any]], says: str) -> None:
    got = sc.compare_results(["r", "s"], [["a/b", 10], ["c/d", 7]], ["r", "s"], rows, "answer")
    assert not got["pass"] and says in got["detail"]


def test_float_noise_in_the_last_digit_is_the_same_cell() -> None:
    assert sc.compare_results(["x"], [[0.1 + 0.2]], ["y"], [[0.3]], "answer")["pass"]


def test_evidence_passes_when_the_agent_rows_contain_the_goldens() -> None:
    g = [["policy A", "t1"]]
    assert sc.compare_results(
        ["p", "t"], g, ["t", "p"], [["t1", "policy A"], ["t2", "B"]], "evidence"
    )["pass"]
    assert not sc.compare_results(["p", "t"], g, ["t", "p"], [["t2", "B"]], "evidence")["pass"]


# ── structure ─────────────────────────────────────────────────────────────────


def test_structure_names_the_first_difference() -> None:
    cat, diff = sc.structure_diff(
        "select a from t join u on t.id = u.id where x > 3",
        "select a from t join u on t.id ilike u.id where x > 3",
    )
    assert cat == "join differs" and "joins" in diff
    cat, _ = sc.structure_diff(
        "select substring(p from 'stars count of ([0-9,]+)') from t",
        "select substring(p from '([0-9]+) stars') from t",
    )
    assert cat == "parse differs"
    assert sc.structure_diff("select 1 from t", "select 1 from u")[0] == "wrong tables"
    assert (
        sc.structure_diff("select a from t order by a limit 5", "select a from t")[0]
        == "order / tie"
    )
    assert sc.structure_diff("select a from t", "select a frm t where")[1] == {"unparsed": "agent"}


def test_cte_names_are_not_tables() -> None:
    shape = sc.sql_shape("with c as (select * from real_table) select * from c")
    assert shape is not None and shape["tables"] == ["real_table"]


# ── one trial, three scores, one category ─────────────────────────────────────


def _golden(kind: str = "answer", sql: str = "select name from t order by name") -> sc._Golden:
    return sc._Golden(7, kind, sql, ["name"], [["a"], ["b"]], None)


def _row(**over: Any) -> dict[str, Any]:
    base = {
        "query_id": "yelp/1",
        "trial": 1,
        "passed": True,
        "agent_sql": "select name from t",
        "mode": "pass_through",
        "step": None,
    }
    return base | over


def _trace(rows: list[list[Any]], cols: list[str] | None = None) -> dict[str, Any]:
    return {"submission": {"columns": cols or ["name"], "rows": rows, "row_count": len(rows)}}


def test_categories() -> None:
    right, wrong = _trace([["b"], ["a"]]), _trace([["a"], ["z"]])
    assert sc.score_trial(_row(), right, _golden(), True)["category"] == "solved"
    got = sc.score_trial(_row(mode="derived", passed=False), right, _golden(), True)
    assert got["category"] == "decision" and got["sql"] and not got["decision"]
    assert got["decision_detail"] == (
        "chose derived; the golden is an answer golden, so pass_through is right"
    )
    assert got["sql_detail"] == "returns the golden's 2 row(s)"
    got = sc.score_trial(_row(passed=False), right, _golden(), True)
    assert got["category"] == "format"
    evid = _golden("evidence")
    got = sc.score_trial(_row(mode="derived", passed=False), right, evid, True)
    assert got["category"] == "derived step wrong" and got["decision"]
    got = sc.score_trial(_row(), wrong, _golden(), True)
    assert got["category"] == "right answer another way" and got["result_diff"]
    got = sc.score_trial(_row(passed=False), wrong, _golden(), True)
    assert got["category"] == "order / tie" and got["sql"] is False
    got = sc.score_trial(
        _row(agent_sql=None, passed=False, error="timeout after 900s"), {}, _golden(), True
    )
    assert got["category"] == "no SQL" and got["sql"] is False and "timeout" in got["detail"]
    got = sc.score_trial(_row(agent_sql=None), {}, None, True)
    assert got["category"] == "no golden" and got["sql"] is None and got["answer"] is True


def test_a_version_without_submit_is_answer_only() -> None:
    got = sc.score_trial(_row(agent_sql=None, mode=None), {}, _golden(), False)
    assert got["sql"] is None and got["decision"] is None
    card = sc.summarise([got], None, submits=False)
    assert card["totals"]["sql"] == {"passed": 0, "n": 0} and card["optimise_first"] == []


def test_totals_carry_their_denominators_and_split() -> None:
    rows = [
        sc.score_trial(_row(query_id="yelp/1"), _trace([["a"], ["b"]]), _golden(), True),
        sc.score_trial(_row(query_id="yelp/2", passed=False), _trace([["a"]]), _golden(), True),
        sc.score_trial(_row(query_id="agnews/1", agent_sql=None, passed=False), {}, None, True),
    ]
    card = sc.summarise(rows, {"train": ["yelp/1"], "heldout": ["yelp/2"]})
    assert card["totals"]["answer"] == {"passed": 1, "n": 3}
    assert card["totals"]["sql"] == {"passed": 1, "n": 2}
    assert card["by_split"]["heldout"]["answer"] == {"passed": 0, "n": 1}
    assert card["optimise_first"] == [{"category": "order / tie", "n": 1, "queries": ["yelp/2"]}]


# ── the split ────────────────────────────────────────────────────────────────


def test_the_committed_split_is_disjoint_and_every_dataset_has_both_sides() -> None:
    train = json.loads((SPLITS_DIR / "train.json").read_text())["queries"]
    held = json.loads((SPLITS_DIR / "heldout.json").read_text())["queries"]
    assert not set(train) & set(held) and len(train) == 33 and len(held) == 16
    assert {q.split("/")[0] for q in held} <= {q.split("/")[0] for q in train}
    assert sc.make_split(train + held) == {"train": train, "heldout": held}  # seeded: reproducible


def test_make_split_keeps_two_thirds_per_dataset() -> None:
    s = sc.make_split([f"d/{i}" for i in range(1, 13)] + ["e/1", "e/2", "f/1"])
    per = {d: sum(q.startswith(d + "/") for q in s["train"]) for d in "def"}
    assert per == {"d": 8, "e": 1, "f": 1}


# ── the guards ───────────────────────────────────────────────────────────────


def test_guards() -> None:
    q = "Which five repositories written in Swift have the most stars and forks together?"
    gold = "repo,lang\nswift-org/swift,Swift\nvapor/vapor,Swift"
    guard = Guard(
        questions=[q],
        golds=[(q, gold)],
        golden_sqls=["select repo_name from gh_repos where lang = 'swift'"],
    )
    assert guard.check("Stars are written three ways; strip commas before casting.") == []
    assert question_runs("five repositories written in swift have the most stars and", [q])
    assert "vapor/vapor" in gold_cells(gold) and "repo" not in gold_cells(gold)
    assert any("gold values" in p for p in guard.check("the top one is vapor/vapor"))
    assert guard.check("the language column says Swift") == []  # the question names it
    assert golden_fragments("use select repo_name from gh_repos where lang", guard.golden_sqls)
    assert not golden_fragments("count ( * ) as n from t", ["select count(*) as n from t"])
    assert any("characters" in p for p in guard.check("x" * 1_501))


# ── what an optimiser session is shown ─────────────────────────────────────────


def test_a_session_sees_only_its_datasets_train_questions() -> None:
    def q(qid: str, ok: bool, golden: bool = True) -> dict[str, Any]:
        return {
            "query_id": qid,
            "answer": ok,
            "sql": ok if golden else None,
            "decision": True if golden else None,
            "golden_id": 1 if golden else None,
            "category": "solved" if ok else "filter differs",
            "detail": "",
            "structure": {},
            "result_diff": [],
        }

    card = {
        "questions": [
            q("yelp/1", False),
            q("yelp/2", True),
            q("yelp/3", False),
            q("bookreview/1", False),
        ]
    }
    results = {
        k: {
            "question": f"QUESTION {k}",
            "agent_sql": f"select '{k}'",
            "reason": "",
            "mode": "pass_through",
        }
        for k in ("yelp/1", "yelp/2", "yelp/3", "bookreview/1")
    }
    goldens = {
        k: {"sql": f"select golden_{k.replace('/', '_')}", "kind": "answer"} for k in results
    }
    msg, failed = briefing(
        "yelp",
        load_version("v1_sql"),
        card,
        results,
        {},
        goldens,
        train={"yelp/1", "yelp/2", "bookreview/1"},
    )
    assert failed == ["yelp/1"]
    assert "QUESTION yelp/1" in msg and "golden_yelp_1" in msg  # D29: train goldens are shown
    assert "QUESTION yelp/2" in msg and "golden_yelp_2" not in msg  # passing: its agent SQL only
    assert "yelp/3" not in msg  # held out
    assert "bookreview" not in msg.split("## Failed")[1]  # another dataset


# ── promotion (D30; with no Pass@1 recorded, D46 falls to answers) ──────────────────────────────────────────────────────────


def test_the_most_answers_passed_wins_and_a_tie_keeps_the_incumbent() -> None:
    from dab_bench.eval.promote import Candidate, decide

    def c(v: str, passed: int | None, why: str = "") -> Candidate:
        return Candidate(v, f"run_{v}", passed, 54, 54, why_not=why)

    assert decide([c("v0", 27), c("v1_sql", 31), c("v2_sql", 30)], "v0")[0] == "v1_sql"
    winner, reason = decide([c("v0", 27), c("v1_sql", 27)], "v0")
    assert winner == "v0" and "tie" in reason
    assert decide([c("v0", 27), c("v1_sql", 33), c("v2_sql", 33)], "v0")[0] == "v1_sql"
    # an incomplete run cannot win, however high its count
    assert decide([c("v0", 27), c("v1_sql", 40, "3 trial(s) not scored")], "v0")[0] == "v0"


def test_a_rounded_agent_number_is_the_goldens_number() -> None:
    got = sc.compare_results(["avg"], [[3.547008547008547]], ["avg"], [[3.55]], "answer")
    assert got["pass"] and "rounding" in got["detail"]
    assert not sc.compare_results(["avg"], [[3.547008547008547]], ["avg"], [[3.54]], "answer")[
        "pass"
    ]
    assert not sc.compare_results(["n"], [["3.5x"]], ["n"], [["3.5"]], "answer")["pass"]


def test_a_bare_word_inside_a_list_cell_is_not_a_gold_value() -> None:
    cells = gold_cells("title,code\nMUSICAL INSTRUMENTS; KEYS,G10\nBAKING; EDIBLE DOUGHS,A21")
    assert "keys" not in cells and "edible doughs" in cells
    assert "musical instruments; keys" in cells  # the whole cell still counts


def test_length_alone_is_not_a_leak() -> None:
    guard = Guard(questions=[], golds=[], golden_sqls=[])
    long = guard.check("x " * 800)
    assert long and guard.leaks(long) == []
    g2 = Guard(questions=[], golds=[("q", "a\nsecret-value")], golden_sqls=[])
    assert g2.leaks(g2.check("the answer is secret-value")) != []
