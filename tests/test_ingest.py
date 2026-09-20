import json
from pathlib import Path

from dab_bench.data.ingest import classify_validator, run


def test_classify_validator_styles() -> None:
    assert (
        classify_validator("from common_scaffold.validate.levenshtein import levenshtein")
        == "levenshtein"
    )
    assert (
        classify_validator("gt = Path(__file__).parent / 'ground_truth.csv'") == "reads-gold-file"
    )
    assert classify_validator("import re\n") == "regex"
    assert classify_validator("gt in llm_output") == "substring"


def test_ingest_fixture_tree(fake_upstream: Path, index_in_tmp: Path) -> None:
    r = run(root=fake_upstream, commit="deadbeef")
    assert (r.datasets_total, r.queries_total) == (2, 3)
    assert (r.datasets_in_scope, r.queries_in_scope) == (1, 2)
    assert r.deferred_datasets == ["cve"] and r.deferred_queries == 1
    # the cve row is out of scope and counted, never dropped silently
    assert r.answer_rows == 3 and r.answer_rows_unmatched == 1
    assert r.warnings == []

    source = json.loads((index_in_tmp / "source.json").read_text())
    assert source["commit"] == "deadbeef"
    assert source["deferred"] == {"datasets": ["cve"], "queries": 1}

    datasets = json.loads((index_in_tmp / "datasets.json").read_text())
    assert [d["key"] for d in datasets] == ["bookreview"]
    d = datasets[0]
    assert d["engines"] == ["postgres", "sqlite"]
    assert d["bytes_total"] == 649048 + 1093632
    assert d["hints"].startswith("Hint:")
    by_name = {db["name"]: db for db in d["dbs"]}
    assert by_name["reviews"]["bytes"] == 1093632 and by_name["reviews"]["in_manifest"] is True

    queries = json.loads((index_in_tmp / "queries.json").read_text())
    assert [q["id"] for q in queries] == ["bookreview/1", "bookreview/2"]
    q1 = queries[0]
    assert q1["question"].startswith("Which decade")
    assert q1["gold_text"] == "2020" and q1["gold_lines"] == 1
    assert q1["validator"]["style"] == "substring"
    assert queries[1]["validator"]["style"] == "regex"
    assert all(q["site_text_matches"] is True for q in queries)

    validators = json.loads((index_in_tmp / "validators.json").read_text())
    assert {s["style"]: s["n"] for s in validators["styles"]} == {
        "regex": 1,
        "reads-gold-file": 0,
        "substring": 1,
        "levenshtein": 0,
    }

    manifest = json.loads((index_in_tmp / "manifest.json").read_text())
    assert sum(m["in_scope"] for m in manifest) == 2
    assert all(m["is_lfs_pointer"] for m in manifest if m["in_scope"])

    lb = json.loads((index_in_tmp / "leaderboard.json").read_text())
    files = lb["answer_files"]
    assert len(files) == 1 and files[0]["name"] == "react_gemini-3-pro"
    assert files[0]["rank"] == 1 and files[0]["rows"] == 3 and files[0]["rows_unmatched"] == 1

    answers = json.loads((index_in_tmp.parent / "answers" / "react_gemini-3-pro.json").read_text())
    assert [a["id"] for a in answers] == ["bookreview/1", "bookreview/1", "bookreview/2"]
    assert all(isinstance(a["run"], int) for a in answers)
    assert "deadbeef" in (index_in_tmp / "ATTRIBUTION.md").read_text()


def test_ingest_warns_when_site_text_differs(fake_upstream: Path, index_in_tmp: Path) -> None:
    site = fake_upstream / "docs/data/queries.json"
    rows = json.loads(site.read_text())
    rows[0]["text"] = "A different wording"
    site.write_text(json.dumps(rows))
    r = run(root=fake_upstream, commit="deadbeef")
    assert any("bookreview/1" in w for w in r.warnings)
