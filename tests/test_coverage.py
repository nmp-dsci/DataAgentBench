"""The committed golden coverage (`dab golden-coverage`): a status per question, no SQL."""

import json

import pytest

from dab_bench.config import SOURCE_PATH
from dab_bench.data.index import load
from dab_bench.eval import golden

pytestmark = pytest.mark.skipif(not SOURCE_PATH.exists(), reason="no committed index")


def test_status_follows_the_golden_tab() -> None:
    assert golden.status_of(None) == "none"
    assert golden.status_of({"kind": "evidence", "passed": None, "gold_match": ""}) == "evidence"
    assert golden.status_of({"kind": "answer", "passed": True, "gold_match": "exact"}) == "exact"
    assert (
        golden.status_of({"kind": "answer", "passed": True, "gold_match": "exact_values"})
        == "exact"
    )
    assert (
        golden.status_of({"kind": "answer", "passed": True, "gold_match": "reordered"}) == "differs"
    )
    assert golden.status_of({"kind": "answer", "passed": False, "gold_match": ""}) == "fails"
    assert golden.how_started("proposal #30") == "proposal"
    assert golden.how_started("20260921T064521Z_v0_all_haiku/yelp/1/t1") == "run"
    assert golden.how_started("") == "hand"


def test_the_committed_coverage_matches_the_index() -> None:
    if not golden.COVERAGE_PATH.exists():
        pytest.skip("no coverage export yet (dab golden-coverage)")
    cov = json.loads(golden.COVERAGE_PATH.read_text())
    ids = [q["id"] for q in load().queries]
    assert [r["id"] for r in cov["queries"]] == ids
    assert cov["n"] == len(ids)
    assert all(r["status"] in golden.STATUSES for r in cov["queries"])
    assert sum(cov["counts"].values()) == cov["n"]
    assert cov["written"] == cov["n"] - cov["counts"]["none"]
    assert not any("sql" in r for r in cov["queries"])
