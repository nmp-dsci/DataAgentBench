"""Fixtures: a tiny fake upstream tree, and the index redirected into tmp_path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dab_bench.data import ingest as ingest_mod

LEADERBOARD = {
    "updatedAt": "2026-09-15",
    "sources": [
        "DEPS_DEV_V1 query 1 re-scored 2026-08-18 under a revised validator",
        "All Pass@1 scores recomputed 2026-06-12 (including the regenerated PATENTS ground truths)",
    ],
    "overallLeaderboard": [
        {
            "rank": 1,
            "agent": "Gemini-3-Pro ReAct",
            "trials": 50,
            "passAt1": 0.5,
            "promptGroup": "general-purpose",
            "team": "EPIC",
            "date": "2026-03-02",
        },
    ],
    "promptqlStratified": {"columns": [], "rows": [], "overall": {}},
    "baselineStratified": {
        "columns": [{"key": "gemini3pro", "label": "Gemini-3-Pro"}],
        "rows": [{"dataset": "bookreview", "gemini3pro": 0.5}],
        "overall": {"dataset": "Average", "gemini3pro": 0.5},
    },
}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def fake_upstream(tmp_path: Path) -> Path:
    """Two datasets: `bookreview` (released, 2 queries) and `cve` (unreleased, 1 query)."""
    root = tmp_path / "upstream"
    # bookreview: sqlite + postgres, one regex validator and one substring validator
    _write(
        root / "query_bookreview/db_config.yaml",
        "db_clients:\n  reviews:\n    db_type: sqlite\n    db_path: query_dataset/review_query.db\n  books:\n    db_type: postgres\n    db_name: bookreview_db\n    sql_file: query_dataset/books_info.sql\n",
    )
    _write(root / "query_bookreview/db_description.txt", "Two databases about books.\n")
    _write(root / "query_bookreview/db_description_withhint.txt", "Hint: join on ISBN.\n")
    _write(
        root / "query_bookreview/query1/query.json",
        json.dumps("Which decade has the highest average rating?"),
    )
    _write(root / "query_bookreview/query1/ground_truth.csv", "2020\n")
    _write(
        root / "query_bookreview/query1/validate.py",
        "def validate(llm_output: str):\n    gt = '2020'\n    return (gt in llm_output, 'ok' if gt in llm_output else 'missing 2020')\n",
    )
    _write(root / "query_bookreview/query2/query.json", json.dumps("How many books?"))
    _write(root / "query_bookreview/query2/ground_truth.csv", "42\n")
    _write(
        root / "query_bookreview/query2/validate.py",
        "import re\n\ndef validate(llm_output: str):\n    nums = re.findall(r'\\d+', llm_output)\n    return ('42' in nums, 'ok' if '42' in nums else 'no 42')\n",
    )
    # LFS pointer stand-ins for the database files
    _write(
        root / "query_bookreview/query_dataset/review_query.db",
        "version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 1093632\n",
    )
    _write(
        root / "query_bookreview/query_dataset/books_info.sql",
        "version https://git-lfs.github.com/spec/v1\noid sha256:def\nsize 649048\n",
    )
    # cve: unreleased
    _write(
        root / "query_cve/db_config.yaml",
        "db_clients:\n  vulns:\n    db_type: sqlite\n    db_path: query_dataset/vulns.db\n",
    )
    _write(root / "query_cve/db_description.txt", "CVE data.\n")
    _write(root / "query_cve/query1/query.json", json.dumps("How many CVEs?"))
    _write(root / "query_cve/query1/ground_truth.csv", "4\n")
    _write(
        root / "query_cve/query1/validate.py",
        "from pathlib import Path\n\ndef validate(llm_output: str):\n    gt = Path(__file__).parent.joinpath('ground_truth.csv').read_text().strip()\n    return (gt in llm_output, '')\n",
    )
    _write(
        root / "dataset_manifest.tsv",
        "query_bookreview/query_dataset/books_info.sql\tdef\t649048\nquery_bookreview/query_dataset/review_query.db\tabc\t1093632\nquery_cve/query_dataset/vulns.db\t123\t20504576\n",
    )
    _write(root / "docs/data/leaderboards.json", json.dumps(LEADERBOARD))
    _write(
        root / "docs/data/queries.json",
        json.dumps(
            [
                {
                    "dataset": "bookreview",
                    "queryId": "query1",
                    "text": "Which decade has the highest average rating?",
                },
                {"dataset": "bookreview", "queryId": "query2", "text": "How many books?"},
            ]
        ),
    )
    # one answer file with three spellings of the dataset and one out-of-scope row
    rows = [
        {"dataset": "bookreview", "query": "1", "run": "0", "answer": "The 2020s"},
        {"dataset": "bookreview", "query": "1", "run": "1", "answer": "the 1990s"},
        {"dataset": "bookreview", "query": "2", "run": 0, "answer": "There are 42 books"},
        {"dataset": "cve", "query": "1", "run": "0", "answer": "4"},
    ]
    _write(root / "submissions/react_gemini-3-pro.json", json.dumps(rows))
    return root


@pytest.fixture
def index_in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every index path the ingest writes at tmp_path/index."""
    idx = tmp_path / "index"
    ans = tmp_path / "answers"
    for name, value in {
        "INDEX_DIR": idx,
        "ANSWERS_DIR": ans,
        "SOURCE_PATH": idx / "source.json",
        "DATASETS_PATH": idx / "datasets.json",
        "QUERIES_PATH": idx / "queries.json",
        "VALIDATORS_PATH": idx / "validators.json",
        "MANIFEST_PATH": idx / "manifest.json",
        "LEADERBOARD_PATH": idx / "leaderboard.json",
        "ATTRIBUTION_PATH": idx / "ATTRIBUTION.md",
    }.items():
        monkeypatch.setattr(ingest_mod, name, value)
    return idx
