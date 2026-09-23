"""Against the committed index: what a bare clone serves."""

import json

import pytest
from fastapi.testclient import TestClient

from dab_bench.config import SOURCE_PATH
from dab_bench.serving.app import create_app

pytestmark = pytest.mark.skipif(not SOURCE_PATH.exists(), reason="no committed index")


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def test_health_names_the_source_commit(client: TestClient) -> None:
    h = client.get("/healthz").json()
    assert h["status"] == "ok" and len(h["source"]["commit"]) == 40


def test_the_twelve_datasets_and_fifty_four_queries(client: TestClient) -> None:
    ds = client.get("/api/datasets").json()
    assert len(ds) == 12 and sum(d["n_queries"] for d in ds) == 54
    qs = client.get("/api/queries").json()
    assert len(qs) == 54 and all(q["gold_lines"] >= 1 for q in qs)


def test_query_detail_carries_gold_validator_and_hints(client: TestClient) -> None:
    q = client.get("/api/queries/crmarenapro/1").json()
    assert q["gold_text"] == "Authority"
    assert "def validate" in q["validator"]["source"]
    assert q["dataset"]["key"] == "crmarenapro" and q["hints"]
    assert q["trials"] is not None and q["trials"]["n"] == 270


def test_deferred_and_unknown_are_404(client: TestClient) -> None:
    assert client.get("/api/queries/cve/1").status_code == 404
    assert client.get("/api/datasets/cve").status_code == 404
    assert client.get("/api/queries/crmarenapro/99").status_code == 404


def test_validators_and_leaderboard(client: TestClient) -> None:
    v = client.get("/api/validators").json()
    assert {s["style"]: s["n"] for s in v["styles"]} == {
        "regex": 33,
        "reads-gold-file": 0,
        "substring": 12,
        "levenshtein": 9,
    }
    lb = client.get("/api/leaderboard").json()
    assert len(lb["overallLeaderboard"]) == 40 and len(lb["answer_files"]) == 11
    # nine committed upstream and pooled; the top two read from their PRs as references
    pooled = [f for f in lb["answer_files"] if f["pooled"]]
    assert len(pooled) == 9 and sum(f["rows"] for f in pooled) == 14480
    refs = {f["name"]: f["rank"] for f in lb["answer_files"] if not f["pooled"]}
    assert refs == {"permute_eq": 1, "oceanbase_lab_scout": 2}


def _a_traced_trial() -> tuple[str, dict[str, object]] | None:
    """The first result row with a trace file among this machine's runs (none in CI)."""
    from dab_bench.config import RUNS_DIR

    for run in sorted(RUNS_DIR.glob("*/results.jsonl")) if RUNS_DIR.exists() else []:
        for line in run.read_text().splitlines():
            row = json.loads(line)
            if row.get("trace_file") and (run.parent / row["trace_file"]).exists():
                return run.parent.name, row
    return None


def test_a_trial_is_addressed_by_its_id_and_the_old_file_route_agrees(client: TestClient) -> None:
    found = _a_traced_trial()
    if found is None:
        pytest.skip("no run folder with a trace on this machine")
    run, row = found
    new = client.get(f"/api/runs/{run}/{row['query_id']}/t{row['trial']}")
    assert new.status_code == 200, new.text
    stem = str(row["trace_file"]).removeprefix("traces/").removesuffix(".json")
    old = client.get(f"/api/runs/{run}/traces/{stem}")
    assert old.status_code == 200
    assert new.json() == old.json()
    assert new.json()["query_id"] == row["query_id"]
    # the trial segment is `t<k>`; anything else, or a trial the run lacks, is a 404
    assert client.get(f"/api/runs/{run}/{row['query_id']}/x{row['trial']}").status_code == 404
    assert client.get(f"/api/runs/{run}/{row['query_id']}/t999").status_code == 404
    assert client.get(f"/api/runs/no_such_run/{row['query_id']}/t1").status_code == 404
