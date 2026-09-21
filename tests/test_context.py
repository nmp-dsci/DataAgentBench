"""The context pack: the curated files carry data facts, never a question; the builder's pure parts.

The leak test runs over whatever packs are committed under data/context/: for
every released query, no 6-word shingle of the question text (normalised)
appears in that dataset's summary.md or pitfalls.md. The curator never sees a
question, so a hit would mean the material itself quoted one.
"""

from __future__ import annotations

import json
import re

import pytest

from dab_bench.agent.prompt import compose_system_prompt, load_context
from dab_bench.config import CONTEXT_DIR, QUERIES_PATH
from dab_bench.context.build import TableMeta, candidate_pairs, collapse_families, render_schema
from dab_bench.context.curate import split_output

SHINGLE = 6


def _words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]", " ", text.lower()).split()


def _shingles(text: str, n: int = SHINGLE) -> set[str]:
    w = _words(text)
    return {" ".join(w[i : i + n]) for i in range(max(0, len(w) - n + 1))}


def _curated_datasets() -> list[str]:
    if not CONTEXT_DIR.exists():
        return []
    return sorted(p.name for p in CONTEXT_DIR.iterdir() if (p / "summary.md").exists())


@pytest.mark.parametrize("dataset", _curated_datasets() or ["(none curated)"])
def test_curated_files_quote_no_question(dataset: str) -> None:
    if dataset == "(none curated)":
        pytest.skip("no curated packs committed")
    pack = (
        (CONTEXT_DIR / dataset / "summary.md").read_text()
        + "\n"
        + (CONTEXT_DIR / dataset / "pitfalls.md").read_text()
    )
    pack_shingles = _shingles(pack)
    questions = [q for q in json.loads(QUERIES_PATH.read_text()) if q["dataset_key"] == dataset]
    assert questions, f"no queries in the index for {dataset}"
    for q in questions:
        hits = _shingles(q["question"]) & pack_shingles
        assert not hits, f"{q['id']} leaks into {dataset}'s curated pack: {sorted(hits)[:3]}"


@pytest.mark.parametrize("dataset", _curated_datasets() or ["(none curated)"])
def test_curated_pack_composes_into_the_system_prompt(dataset: str) -> None:
    if dataset == "(none curated)":
        pytest.skip("no curated packs committed")
    ctx = load_context(dataset)
    assert ctx.summary.strip() and ctx.tables
    prompt = compose_system_prompt("BEHAVIOUR", ctx, hints=False)
    assert prompt.startswith("BEHAVIOUR")
    assert f"# Dataset: {dataset}" in prompt
    assert "## Hints" not in prompt
    with_hints = compose_system_prompt("BEHAVIOUR", ctx, hints=True)
    assert ("## Hints" in with_hints) == bool(ctx.hints.strip())
    assert len(ctx.context_sha) == 12


def test_split_output_reads_the_two_markers() -> None:
    text = "preamble\n=== summary.md ===\nS line\n=== pitfalls.md ===\n- p1\n- p2\n"
    s, p = split_output(text)
    assert s == "S line\n"
    assert p == "- p1\n- p2\n"
    assert split_output("no markers") == ("", "")


def _t(store: str, table: str, cols: list[tuple[str, str]], rows: int = 10) -> TableMeta:
    return TableMeta(store, table.split("_", 1)[1], table, rows, cols)


def test_candidate_pairs_know_a_bare_id_by_its_table() -> None:
    account = _t("crm", "crm_account", [("Id", "text"), ("Name", "text")])
    order = _t("crm", "crm_order", [("Id", "text"), ("AccountId", "text"), ("Name", "text")])
    pairs = {(a.table, ca, b.table, cb) for a, ca, b, cb in candidate_pairs([account, order])}
    assert ("crm_account", "Id", "crm_order", "AccountId") in pairs
    assert ("crm_account", "Id", "crm_order", "Id") not in pairs  # two bare ids never pair
    assert ("crm_account", "Name", "crm_order", "Name") in pairs  # same-name columns do


def test_candidate_pairs_match_ref_to_id() -> None:
    business = _t("m", "yelp_business", [("business_id", "text")])
    review = _t("d", "yelp_review", [("business_ref", "text"), ("text", "text")])
    pairs = candidate_pairs([business, review])
    assert [(ca, cb) for _, ca, _, cb in pairs] == [("business_id", "business_ref")]


def test_families_collapse_identical_signatures() -> None:
    cols = [("Date", "text"), ("Close", "double precision")]
    tickers = [_t("trade", f"sm_t{i}", cols, rows=i) for i in range(12)]
    union = TableMeta(
        "trade", "*(12 tables)", "sm_stocktrade_all", 120, [("_table", "text"), *cols]
    )
    info = _t("info", "sm_info", [("Symbol", "text")])
    kept, fams = collapse_families([*tickers, union, info])
    assert {t.table for t in kept} == {"sm_stocktrade_all", "sm_info"}
    assert len(fams) == 1 and len(fams[0].members) == 12
    assert fams[0].representative.table == "sm_t11" and fams[0].union_table == "sm_stocktrade_all"
    md = render_schema("sm", kept, fams)
    assert "family of 12 tables" in md and "sm_stocktrade_all" in md
