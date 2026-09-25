"""Round 2's optimiser (plan s08, D32 B): the playbook in system.md, the component groups and
what a component session is shown. No model, no Postgres."""

from __future__ import annotations

from typing import Any

from dab_bench.agent import optimise as op
from dab_bench.agent.versions import load_version
from dab_bench.eval.ledger import COMPONENTS, clean_lines, clean_verdicts


def test_the_skeleton_is_appended_once_with_seven_empty_sections() -> None:
    base = load_version("v2_sql").system_prompt
    md = op.with_playbook(base)
    assert md.startswith(base.rstrip()) and op.PLAYBOOK_HEAD in md
    assert op.with_playbook(md) == md  # never twice
    assert list(op.sections(md)) == list(COMPONENTS)
    assert all(body == "" for body in op.sections(md).values())
    assert "plan" in md.split(op.PLAYBOOK_HEAD)[1]  # the skeleton asks for the plan first


def test_filling_a_section_keeps_the_others_and_their_order() -> None:
    md = op.with_playbook("You answer with SQL.\n")
    md = op.fill_sections(md, {"keys": "- strip a prefix before joining", "rank": "- break ties"})
    md = op.fill_sections(md, {"parse": "- read every phrasing"})
    got = op.sections(md)
    assert got["keys"] == "- strip a prefix before joining" and got["rank"] == "- break ties"
    assert got["parse"] == "- read every phrasing" and got["sources"] == ""
    assert md.index("strip a prefix") < md.index("read every phrasing") < md.index("break ties")
    assert op.fill_sections("no playbook here\n", {"keys": "x"}) == "no playbook here\n"


def test_the_section_budget_keeps_system_md_under_the_cap() -> None:
    md = op.with_playbook(load_version("v2_sql").system_prompt)
    comps = list(COMPONENTS)
    b = op.section_budget(md, comps)
    assert b == op.SECTION_MAX  # every section gets the full 600, even all seven at once
    full = op.fill_sections(md, dict.fromkeys(comps, "x" * b))
    assert len(full) <= op.PLAYBOOK_SYSTEM_MAX
    assert op.section_budget(md, ["keys"]) == op.SECTION_MAX  # one section: the section cap


def _row(qid: str, breaks: str | None, split_ok: bool = False, **kw: Any) -> dict[str, Any]:
    verdicts = clean_verdicts({breaks: "differs"} if breaks else {})
    row = {
        "query_id": qid,
        "trial": 1,
        "answer": split_ok,
        "sql": False,
        "decision": True,
        "golden_id": 1,
        "category": f"breaks at {breaks}" if breaks else "no SQL",
        "breaks_at": breaks,
        "detail": "returns 1 row(s); the golden returns 2",
        "sql_detail": "returns 1 row(s); the golden returns 2",
        "result_diff": [],
        "ledger": {
            "golden": clean_lines({"parse": "reads three phrasings"}),
            "agent": clean_lines({"parse": "reads one phrasing"}),
            "verdicts": verdicts,
            "breaks_at": breaks,
            "why": "one phrasing of three",
        }
        if breaks
        else {},
    }
    return row | kw


def test_components_group_failed_train_questions_across_datasets() -> None:
    card = {
        "questions": [
            _row("yelp/2", "parse"),
            _row("patents/2", "parse"),
            _row("patents/1", "sources"),  # held out: never read
            _row("crmarenapro/2", None),  # no SQL: a dataset session reads it, no component
            _row("yelp/1", None, sql=True, answer=True, category="solved"),
        ]
    }
    failed = op.failed_train(card, {"yelp/2", "patents/2", "crmarenapro/2", "yelp/1"})
    assert [q["query_id"] for q in failed] == ["yelp/2", "patents/2", "crmarenapro/2"]
    groups = op.by_component(failed)
    assert list(groups) == ["parse"]
    assert [q["query_id"] for q in groups["parse"]] == ["yelp/2", "patents/2"]


def test_a_component_session_reads_its_step_for_every_question() -> None:
    rows = [_row("yelp/2", "parse"), _row("patents/2", "parse")]
    results = {
        q["query_id"]: {"question": f"QUESTION {q['query_id']}", "agent_sql": "select agent_x"}
        for q in rows
    }
    goldens = {q["query_id"]: {"sql": "select golden_x", "kind": "answer"} for q in rows}
    msg = op.component_briefing("parse", rows, results, goldens, "SYSTEM MD", "", 420)
    assert "QUESTION yelp/2" in msg and "QUESTION patents/2" in msg
    assert "dataset yelp" in msg and "dataset patents" in msg
    assert "reference: reads three phrasings | agent: reads one phrasing" in msg
    assert "select golden_x" in msg and "select agent_x" in msg  # D29: train goldens are shown
    assert "420 characters" in msg and "SYSTEM MD" in msg and "(empty)" in msg


def test_a_dataset_briefing_leads_with_the_ledger() -> None:
    row = _row("yelp/2", "parse", structure={"joins": {"golden": ["a"], "agent": ["b"]}})
    card = {"questions": [row]}
    results = {
        "yelp/2": {"question": "Q", "agent_sql": "select 1", "reason": "", "mode": "pass_through"}
    }
    msg, failed = op.briefing(
        "yelp",
        load_version("v2_sql"),
        card,
        results,
        {},
        {"yelp/2": {"sql": "select 2", "kind": "answer"}},
        {"yelp/2"},
    )
    assert failed == ["yelp/2"]
    assert "Where the statement breaks (the ledger): parse" in msg
    assert "Structure differences" not in msg  # the ledger replaces the sqlglot line
