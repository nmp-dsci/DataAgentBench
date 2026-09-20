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


def test_summary_lists_are_consistent() -> None:
    t = json.loads(TRIALS_PATH.read_text())
    s = t["summary"]
    assert set(s["never_passed"]) <= set(s["under_10pct"])
    for qid in s["never_passed"]:
        assert t["per_query"][qid]["passed"] == 0
