"""Plan s11: a round that reads every error (D38), the guards G1–G4 (D40 B), the cross-fit and
the leaderboard's answer file. No model, no Postgres: the reviewer's session is replaced where a
test needs a verdict."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import mcp.types as mcp_types
import pytest
import yaml

from dab_bench.agent import optimise as op
from dab_bench.agent import versions
from dab_bench.agent.prompt import load_context
from dab_bench.agent.tools import ToolState
from dab_bench.data.index import load
from dab_bench.eval import crossfit as cf
from dab_bench.eval import guards, review
from dab_bench.eval.guards import Guard


async def _call(server: Any, name: str, args: dict[str, Any]) -> mcp_types.CallToolResult:
    h = server._request_handlers["tools/call"].handler
    return await h(None, mcp_types.CallToolRequestParams(name=name, arguments=args))


def _server(guard: Guard, **kw: Any) -> tuple[op.Session, Any]:
    sess = op.Session(scope="yelp")
    state = ToolState(dataset="yelp", ctx=load_context("yelp"), trial_key="t", sandbox=None)
    return sess, op._server(state, sess, guard, "yelp", **kw)["instance"]


# ── G4: no text names a question ────────────────────────────────────────────


def test_g4_refuses_prompt_text_that_names_a_question_but_not_a_quarter() -> None:
    g = Guard(max_chars=2_000, datasets=["yelp", "crmarenapro"], routing=True)
    assert any(p.startswith("G4") for p in g.check("For yelp/3, read the city first."))
    assert any(p.startswith("G4") for p in g.check("In query 3 the ranking is by count."))
    assert g.check("Quarters run Q1 to Q4; a fiscal Q3 2024 starts in July.") == []
    # the rationale may cite ids (G3 asks it to): G4 checks prompt text only
    assert g.check("from yelp/3 and crmarenapro/2", prompt_text=False) == []
    assert Guard(max_chars=2_000, datasets=["yelp"]).check("For yelp/3 …") == []  # off by default


def test_format_fixes_do_not_count_as_leaks() -> None:
    assert not guards.is_leak("2,100 characters; the limit is 2,000")
    assert not guards.is_leak("G3 cite, in the rationale, at least two of the questions …")
    assert guards.is_leak("G1 decisive for yelp/3: …")
    assert guards.is_leak("G4 a question named (yelp/3): …")
    assert guards.is_leak("gold values written literally: …")


# ── G2: the whole-prompt audit ──────────────────────────────────────────────


def test_g2_finds_a_planted_gold_value_and_reports_counts_only() -> None:
    golds = [("Which city has the most reviews?", "city\nPhiladelphia")]
    units = {"notes:yelp": "Cities are stored in title case.", "playbook:rank": ""}
    assert guards.audit(units, golds) == {}
    units["notes:yelp"] += " The busiest is Philadelphia."
    got = guards.audit(units, golds)
    assert got == {"notes:yelp": 1} and "Philadelphia" not in json.dumps(got)


def test_no_version_prompt_holds_a_gold_value() -> None:
    """LabRat's reverse gate over every version's prompt surfaces: every gold value of the 54
    searched in system.md and every dataset's notes."""
    golds = [(q["question"], q.get("gold_text") or "") for q in load().queries if q["released"]]
    for name in versions.list_versions():
        v = versions.load_version(name)
        units = {"system.md": v.system_prompt} | {f"notes:{d}": t for d, t in v.notes.items()}
        assert guards.audit(units, golds) == {}, name


# ── G3: a section generalises from two or more errors ───────────────────────


@pytest.mark.anyio
async def test_g3_asks_the_rationale_to_cite_two_questions_and_is_not_a_leak() -> None:
    sess, server = _server(
        Guard(max_chars=600), tool_name="write_section", cite_from=["yelp/2", "patents/3"]
    )
    bad = await _call(
        server, "write_section", {"notes": "- read every phrasing", "rationale": "from yelp/2"}
    )
    assert bad.is_error and sess.refusals[0]["problems"][0].startswith("G3")
    bad2 = await _call(
        server, "write_section", {"notes": "- read every phrasing", "rationale": "yelp/2 only"}
    )
    assert bad2.is_error and not sess.dropped  # a format fix never drops the section
    ok = await _call(
        server,
        "write_section",
        {"notes": "- read every phrasing", "rationale": "yelp/2 and patents/3 both read one"},
    )
    assert not ok.is_error and sess.notes == "- read every phrasing"


def test_g3_gives_a_step_a_section_only_when_two_errors_break_there() -> None:
    groups = {
        "parse": [{"query_id": "yelp/2"}, {"query_id": "patents/3"}],
        "rank": [{"query_id": "crmarenapro/4"}],
    }
    kept, skipped = op.breadth(groups)
    assert list(kept) == ["parse"] and skipped == {"rank": ["crmarenapro/4"]}


def test_the_g3_briefing_asks_the_session_for_its_citations() -> None:
    """The component session's message is the generated prompt it receives."""
    msg = op.component_briefing("parse", [], {}, {}, "SYSTEM", "", 600, cite=True)
    assert "cite by id" in msg and "at least two" in msg
    assert "cite by id" not in op.component_briefing("parse", [], {}, {}, "S", "", 600)


# ── G1: the reviewer's verdict refuses a write ──────────────────────────────


@pytest.mark.anyio
async def test_g1_a_decisive_verdict_refuses_the_write_and_is_recorded() -> None:
    calls: list[str] = []

    async def reviewer(text: str) -> tuple[list[str], dict[str, Any]]:
        calls.append(text)
        if "cutoff" in text:
            return ["G1 decisive for yelp/3: the cutoff"], {"reviewed": True, "decisive": True}
        return [], {"reviewed": True, "decisive": False}

    sess, server = _server(Guard(max_chars=2_000), reviewer=reviewer)
    r = await _call(server, "write_notes", {"notes": "Use a cutoff of forty.", "rationale": "x"})
    assert r.is_error and sess.refusals[0]["problems"][0].startswith("G1")
    r = await _call(
        server, "write_notes", {"notes": "Stars come in three phrasings.", "rationale": "x"}
    )
    assert (
        not r.is_error
        and len(calls) == 2
        and [x["decisive"] for x in sess.reviews] == [True, False]
    )


@pytest.mark.anyio
async def test_g1_runs_after_the_cheap_checks() -> None:
    async def reviewer(text: str) -> tuple[list[str], dict[str, Any]]:
        raise AssertionError("the reviewer must not see text the literal guard refuses")

    sess, server = _server(Guard(max_chars=10), reviewer=reviewer)
    r = await _call(server, "write_notes", {"notes": "far too long for ten", "rationale": "x"})
    assert r.is_error and sess.reviews == []


@pytest.mark.anyio
async def test_the_reviewer_is_shown_the_text_and_every_gold_and_redacts_its_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dab_bench.eval import ledger

    qs = review.questions_for("yelp")
    gold = next(q.gold for q in qs if q.gold.strip())
    value = gold.strip().splitlines()[-1].split(",")[0].strip()
    seen: dict[str, str] = {}

    async def fake_ask(system_prompt: str, message: str, schema: Any, **kw: Any) -> Any:
        seen["message"], seen["agent"], seen["tool"] = message, kw["agent"], kw["tool_name"]
        return ledger.Call(
            out={
                "decisive": True,
                "question": qs[0].qid,
                "what": f"it names {value}",
                "reason": "r",
            }
        )

    monkeypatch.setattr(ledger, "ask", fake_ask)
    problems, rec = await review.review("Some notes.", "dataset", "yelp")
    assert "Some notes." in seen["message"] and all(q.qid in seen["message"] for q in qs)
    assert (seen["agent"], seen["tool"]) == ("reviewer", "write_verdict")
    assert problems and problems[0].startswith(f"G1 decisive for {qs[0].qid}")
    if len(value) >= 4 and not value.replace(".", "").isdigit():
        assert value not in problems[0] and value not in rec["what"]


def test_a_failed_review_is_recorded_as_unreviewed_not_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from dab_bench.eval import ledger

    async def fake_ask(*a: Any, **kw: Any) -> Any:
        return ledger.Call(error="timeout after 300s")

    monkeypatch.setattr(ledger, "ask", fake_ask)
    problems, rec = asyncio.run(review.review("notes", "component", None))
    assert problems == [] and rec["reviewed"] is False


# ── every error read (D38) ──────────────────────────────────────────────────


def _row(qid: str, ok: bool, golden: bool = True) -> dict[str, Any]:
    return {
        "query_id": qid,
        "trial": 1,
        "answer": ok,
        "sql": ok if golden else None,
        "decision": True if golden else None,
        "golden_id": 1 if golden else None,
        "category": "solved" if ok else ("no golden" if not golden else "breaks at parse"),
        "detail": "",
        "structure": {},
        "result_diff": [],
    }


def test_reading_every_error_includes_wrong_answers_without_a_golden() -> None:
    card = {"questions": [_row("agnews/2", False, golden=False), _row("yelp/1", False)]}
    everyone = {"agnews/2", "yelp/1"}
    assert [q["query_id"] for q in op.failed_train(card, everyone)] == ["yelp/1"]
    got = op.failed_train(card, everyone, no_golden=True)
    assert [q["query_id"] for q in got] == ["agnews/2", "yelp/1"]


def test_a_wrong_answer_without_a_golden_is_briefed_without_its_validator_text() -> None:
    card = {"questions": [_row("agnews/2", False, golden=False)]}
    results = {
        "agnews/2": {
            "question": "QUESTION agnews/2",
            "agent_sql": "select 1",
            "answer": "Sports",
            "reason": "SECRET-GOLD expected World",
            "mode": "derived",
        }
    }
    msg, failed = op.briefing(
        "agnews", versions.load_version("v6_sql"), card, results, {}, {}, {"agnews/2"}, True
    )
    assert failed == ["agnews/2"] and "no reference statement" in msg and "Sports" in msg
    assert "SECRET-GOLD" not in msg and "## Failed questions (1)" in msg


# ── the cross-fit ───────────────────────────────────────────────────────────


def test_folds_are_seeded_stratified_and_balanced() -> None:
    qids = [q["id"] for q in load().queries if q["released"]]
    fs = cf.folds(qids, 3)
    assert fs == cf.folds(list(reversed(qids)), 3)  # the same seed gives the same folds
    assert sorted(q for f in fs for q in f) == sorted(qids)
    assert max(map(len, fs)) - min(map(len, fs)) <= 1
    for ds in {q.split("/")[0] for q in qids}:
        per = [sum(1 for q in f if q.startswith(ds + "/")) for f in fs]
        assert max(per) - min(per) <= 1, ds  # every dataset spread as evenly as it can be


def test_pass_at_1_is_the_mean_over_datasets_of_their_pass_rates() -> None:
    got = cf.pass_at_1({"a/1": True, "a/2": False, "b/1": True, "c/1": None})
    assert got == pytest.approx((0.5 + 1.0) / 2)


def test_stitch_scores_each_question_once_by_its_own_fold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cf, "RUNS_DIR", tmp_path)
    for run, rows in {
        "r1": [("a/1", True, True), ("b/1", True, None), ("a/2", False, False)],
        "r2": [("a/2", True, True), ("a/1", False, False)],
    }.items():
        (tmp_path / run).mkdir()
        qs = [{"query_id": q, "trial": 1, "answer": a, "sql": s} for q, a, s in rows]
        (tmp_path / run / "scorecard.json").write_text(json.dumps({"questions": qs}))
    out = cf.stitch([["a/1", "b/1"], ["a/2"]], ["r1", "r2"])
    assert out["questions"]["a/1"] == {"fold": 1, "answer": True, "sql": True}
    assert out["questions"]["a/2"] == {"fold": 2, "answer": True, "sql": True}
    assert out["answer"] == {"passed": 3, "n": 3} and out["sql"] == {"passed": 2, "n": 2}


def test_a_crossfit_fold_is_outside_every_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, extra in (
        ("v9_sql", {}),
        ("v9_sql_f1", {"crossfit_of": "v9_sql", "crossfit_fold": 1}),
    ):
        d = tmp_path / name
        d.mkdir()
        (d / "system.md").write_text("x")
        (d / "agent.yaml").write_text(yaml.safe_dump({"model": "opus", **extra}))
    monkeypatch.setattr(versions, "AGENTS_DIR", tmp_path)
    assert versions.list_versions() == ["v9_sql"]
    assert versions.load_version("v9_sql_f1").config.crossfit_fold == 1  # its eval loads it
    from dab_bench.eval import rounds

    (tmp_path / "v9_sql_f1" / "optimise.json").write_text(json.dumps({"crossfit": {"fold": 1}}))
    (tmp_path / "v9_sql" / "optimise.json").write_text(json.dumps({"started_at": "x"}))
    monkeypatch.setattr(rounds, "AGENTS_DIR", tmp_path)
    assert [r["version"] for r in rounds.round_records()] == ["v9_sql"]


def test_the_answer_file_is_in_the_leaderboards_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cf, "RUNS_DIR", tmp_path)
    (tmp_path / "r").mkdir()
    rows = [
        {"query_id": "deps_dev_v1/1", "trial": 1, "answer": "a"},
        {"query_id": "bookreview/2", "trial": 2, "answer": "b"},
    ]
    (tmp_path / "r" / "results.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    path, n = cf.export_submission("r")
    got = json.loads(Path(path).read_text())
    assert n == 2 and got == [
        {"dataset": "DEPS_DEV_V1", "query": "1", "run": "0", "answer": "a"},
        {"dataset": "bookreview", "query": "2", "run": "1", "answer": "b"},
    ]
