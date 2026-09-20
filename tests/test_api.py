"""Against the committed index: what a bare clone serves."""

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
    assert len(lb["overallLeaderboard"]) == 40 and len(lb["answer_files"]) == 9
    assert sum(f["rows"] for f in lb["answer_files"]) == 14480
