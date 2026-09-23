"""The rescore reproduces the site's own per-dataset tables, or it is not trusted.

The site re-scored on 2026-06-12 under the validators of that day. Ours run
under the ingested commit. The only validator changed since is DEPS_DEV_V1
query 1 (2026-08-18, issue #86), so that dataset is allowed to differ and every
other one must match to two decimals.
"""

import json

import pytest

from dab_bench.config import TRIALS_PATH

pytestmark = pytest.mark.skipif(not TRIALS_PATH.exists(), reason="not rescored")

TOLERATED = {"deps_dev_v1"}

# Overall Pass@1 per answer file against the leaderboard row it is. Permute EQ (#95)
# was scored by the site on its "## Answer" section plus two hand corrections the PR
# describes (a DEPS_DEV_V1 q1 run and a bookreview trial); neither rule is mechanical,
# so the full-text rescore, the rule every other file gets, lands at 256/270 against
# the site's 258/270.
TOLERATED_OVERALL = {"permute_eq": 0.02}


def test_site_tables_reproduce() -> None:
    t = json.loads(TRIALS_PATH.read_text())
    assert t["summary"]["rows"] == 14480 and t["summary"]["queries"] == 54
    bad = []
    for fname, chk in t["site_check"]["files"].items():
        for ds, c in chk["per_dataset"].items():
            if ds in TOLERATED:
                continue
            if abs(c["ours"] - c["site"]) > 0.0051:
                bad.append((fname, ds, c))
    assert bad == [], bad


def test_overall_pass_at_1_reproduces() -> None:
    t = json.loads(TRIALS_PATH.read_text())
    overall = t["site_check"]["overall"]
    assert {"permute_eq", "oceanbase_lab_scout"} <= set(overall)
    bad = {f: c for f, c in overall.items() if abs(c["diff"]) > TOLERATED_OVERALL.get(f, 0.0051)}
    assert bad == {}, bad


def test_reference_files_stay_out_of_the_pooled_rate() -> None:
    t = json.loads(TRIALS_PATH.read_text())
    for q in t["per_query"].values():
        pooled = [
            f for name, f in q["files"].items() if name not in ("permute_eq", "oceanbase_lab_scout")
        ]
        assert q["n"] == sum(f["n"] for f in pooled)
        assert q["passed"] == sum(f["passed"] for f in pooled)
        assert q["files"]["permute_eq"]["n"] == 5


def test_summary_lists_are_consistent() -> None:
    t = json.loads(TRIALS_PATH.read_text())
    s = t["summary"]
    assert set(s["never_passed"]) <= set(s["under_10pct"])
    for qid in s["never_passed"]:
        assert t["per_query"][qid]["passed"] == 0
