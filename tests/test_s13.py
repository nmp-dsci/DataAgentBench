"""Plan s13: the champion lock, each round's outcome, and the history a round reads (built from
MLflow, D42 A). A synthetic lineage in tmp_path — a base version, a model switch, the champion
(a round) and a round from it that lost — stands in for runs/ and agents/. No model, no
Postgres, no MLflow server: a stand-in client serves the same files as MLflow artifacts."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from dab_bench.agent import optimise as op
from dab_bench.agent import versions
from dab_bench.eval import history as hist
from dab_bench.eval import outcome

PLAYBOOK = "## From the question to the statement\n\n### 1 · sources — where\n\n{src}\n\n### 5 · metric — what\n\nMeasure at the grain asked.\n"
SECRET = "SECRET-ANSWER-7"  # a passing answer to a question with no golden: never read (H1)

# question -> per version (answer, sql, breaks_at); sql None = no golden
GRID: dict[str, dict[str, tuple[bool | None, bool | None, str | None]]] = {
    "yelp/1": {  # passed under a and b; the champion's round changed its notes and section
        "a_sql": (True, True, None),
        "b_sql": (True, True, None),
        "c_sql": (False, False, "sources"),
        "d_sql": (False, False, "sources"),
    },
    "yelp/2": {  # never passed; the lost round fixed it
        "a_sql": (False, False, "sources"),
        "b_sql": (False, False, "sources"),
        "c_sql": (False, False, "sources"),
        "d_sql": (True, True, None),
    },
    "agnews/1": {  # no golden; flipped on the model switch alone
        "a_sql": (True, None, None),
        "b_sql": (False, None, None),
        "c_sql": (False, None, None),
        "d_sql": (False, None, None),
    },
    "patents/1": {  # broke at metric, a section no round touched: noise or a side effect
        "a_sql": (True, True, None),
        "b_sql": (True, True, None),
        "c_sql": (False, False, "metric"),
        "d_sql": (False, False, "metric"),
    },
    "patents/2": {  # passing under the champion; the lost round broke it at sources
        "a_sql": (True, True, None),
        "b_sql": (True, True, None),
        "c_sql": (True, True, None),
        "d_sql": (True, False, "sources"),
    },
}
VERSIONS = {
    # name: (model, parent key, parent, notes for yelp, sources section, started_at)
    "a_sql": ("haiku", None, None, "- yelp fact one", "Pick by meaning.", "2026-09-01T00:00:00"),
    "b_sql": (
        "sonnet",
        "measured_against",
        "a_sql",
        "- yelp fact one",
        "Pick by meaning.",
        "2026-09-02T00:00:00",
    ),
    "c_sql": (
        "opus",
        "challenger_of",
        "b_sql",
        "- yelp fact two",
        "Check the union covers every key.",
        "2026-09-03T00:00:00",
    ),
    "d_sql": (
        "opus",
        "challenger_of",
        "c_sql",
        "- yelp fact two",
        "A new sources rule.",
        "2026-09-04T00:00:00",
    ),
}


def _run_id(v: str) -> str:
    return f"run_{v}"


def _lineage(tmp: Path, long_notes: bool = False) -> tuple[Path, Path]:
    runs, agents = tmp / "runs", tmp / "agents"
    for v, (model, key, parent, notes, src, started) in VERSIONS.items():
        d = runs / _run_id(v)
        (d / "agent" / "datasets").mkdir(parents=True)
        cfg: dict[str, Any] = {"model": model}
        if key:
            cfg[key] = parent
        (d / "agent" / "agent.yaml").write_text(yaml.safe_dump(cfg))
        (d / "agent" / "system.md").write_text(
            "Answer with one statement.\n\n" + PLAYBOOK.format(src=src)
        )
        body = notes + ("\n- " + "long fact " * 300 if long_notes and v == "b_sql" else "")
        (d / "agent" / "datasets" / "yelp.md").write_text(body + "\n")
        (d / "run.json").write_text(
            json.dumps(
                {
                    "run_id": _run_id(v),
                    "agent": v,
                    "split": "all",
                    "dry_run": False,
                    "started_at": started,
                    "summary": {"n": 5, "scored": 5},
                }
            )
        )
        qs, res = [], []
        for q, per in GRID.items():
            a, s, brk = per[v]
            qs.append(
                {
                    "query_id": q,
                    "trial": 1,
                    "answer": a,
                    "sql": s,
                    "decision": s,
                    "breaks_at": brk,
                    "category": "solved" if a else "wrong",
                    "golden_id": None if s is None else 1,
                }
            )
            res.append(
                {
                    "query_id": q,
                    "trial": 1,
                    "agent_sql": f"select 1 -- {v} {q}",
                    "answer": SECRET if q == "agnews/1" else "x",
                }
            )
        (d / "scorecard.json").write_text(json.dumps({"questions": qs}))
        (d / "results.jsonl").write_text("\n".join(json.dumps(r) for r in res) + "\n")
    rounds = {
        "c_sql": {
            "challenger_of": "b_sql",
            "sessions": [
                {
                    "scope": "yelp",
                    "kind": "dataset",
                    "questions": ["yelp/2"],
                    "notes": "- yelp fact two",
                    "rationale": "r",
                    "refusals": [],
                }
            ],
        },
        "d_sql": {
            "challenger_of": "c_sql",
            "sessions": [
                {
                    "scope": "yelp",
                    "kind": "dataset",
                    "questions": ["yelp/1"],
                    "notes": None,
                    "rationale": "",
                    "refusals": [
                        {
                            "problems": [
                                "gold values written literally: Philadelphia",
                                "G1 decisive for yelp/1: the city",
                            ]
                        }
                    ],
                },
                {
                    "scope": "playbook:sources",
                    "kind": "component",
                    "questions": ["yelp/1"],
                    "notes": "A new sources rule.",
                    "rationale": "from yelp/1",
                    "refusals": [],
                },
            ],
        },
    }
    for v, rec in rounds.items():
        (agents / v).mkdir(parents=True)
        rec |= {
            "version": v,
            "source_run": _run_id(str(rec["challenger_of"])),
            "started_at": VERSIONS[v][5],
            "mlflow_run_id": f"mlf_{v}",
        }
        (agents / v / "optimise.json").write_text(json.dumps(rec))
    proms = [
        {
            "at": "p1",
            "incumbent": "a_sql",
            "winner": "c_sql",
            "reason": "",
            "candidates": [
                {"version": "a_sql", "run_id": _run_id("a_sql")},
                {"version": "c_sql", "run_id": _run_id("c_sql")},
            ],
        },
        {
            "at": "p2",
            "incumbent": "c_sql",
            "winner": "c_sql",
            "reason": "",
            "candidates": [
                {"version": "c_sql", "run_id": _run_id("c_sql")},
                {"version": "d_sql", "run_id": _run_id("d_sql")},
            ],
        },
    ]
    (agents / "promotions.jsonl").write_text("\n".join(json.dumps(p) for p in proms) + "\n")
    return runs, agents


@pytest.fixture
def lineage(tmp_path: Path) -> tuple[Path, Path]:
    return _lineage(tmp_path)


def _history(lineage: tuple[Path, Path]) -> dict[str, Any]:
    return hist.build(hist.FolderSource(*lineage), "c_sql")


# ── outcomes (B2) ────────────────────────────────────────────────────────────


def test_a_round_that_won_and_one_that_lost_with_what_each_gained_and_lost(
    lineage: tuple[Path, Path],
) -> None:
    runs, agents = lineage
    got = {rec["version"]: out for rec, out in outcome.all_outcomes(agents, runs)}
    assert got["c_sql"]["outcome"] == "won" and got["d_sql"]["outcome"] == "lost"
    d = got["d_sql"]["vs_parent"]
    assert d["sql"]["gained"] == ["yelp/2"] and d["sql"]["lost"] == ["patents/2"]
    assert d["sql"]["lost_breaks_at"] == {"patents/2": "sources"}
    assert (d["answer"]["before"], d["answer"]["after"], d["answer"]["n"]) == (1, 2, 5)
    pending = outcome.round_outcome(
        {"version": "d_sql", "source_run": "run_c_sql"}, [], lambda r: None
    )
    assert pending["outcome"] == "pending" and pending["vs_parent"] == {}


# ── the history (B4) ─────────────────────────────────────────────────────────


def test_the_lineage_the_attempt_and_what_changed(lineage: tuple[Path, Path]) -> None:
    h = _history(lineage)
    assert [(v["version"], v["role"]) for v in h["versions"]] == [
        ("a_sql", "lineage"),
        ("b_sql", "lineage"),
        ("c_sql", "champion"),
        ("d_sql", "attempt"),
    ]
    ch = {v["version"]: v["change"] for v in h["versions"]}
    assert ch["a_sql"]["kind"] == "base" and ch["b_sql"]["kind"] == "model"
    assert ch["c_sql"]["kind"] == "round" and ch["c_sql"]["notes_changed"] == ["yelp"]
    assert ch["c_sql"]["sections_changed"] == ["sources"] and ch["c_sql"]["read"] == {
        "yelp/2": ["yelp"]
    }
    assert [a["version"] for a in h["attempts"]] == ["d_sql"]


def test_status_and_every_flip_labelled(lineage: tuple[Path, Path]) -> None:
    qs = _history(lineage)["questions"]
    assert {q: x["status"] for q, x in qs.items()} == {
        "yelp/1": "regressed",
        "yelp/2": "never",
        "agnews/1": "regressed",
        "patents/1": "regressed",
        "patents/2": "passing",
    }
    flips = {
        q: {e["version"]: e.get("flip") for e in x["timeline"] if e.get("flip")}
        for q, x in qs.items()
    }
    assert flips["agnews/1"] == {"b_sql": "model switch; prompt unchanged"}
    assert flips["yelp/1"] == {"c_sql": "prompt changed for it"}
    assert flips["patents/1"]["c_sql"].startswith("no change to its notes or break-step section")
    assert qs["yelp/1"]["tracked"] == "answer" and qs["patents/2"]["tracked"] == "sql"


def test_the_last_pass_the_diffs_since_and_its_own_statement(lineage: tuple[Path, Path]) -> None:
    lp = _history(lineage)["questions"]["yelp/1"]["last_passed"]
    assert lp["version"] == "b_sql" and lp["sql"] == "select 1 -- b_sql yelp/1"
    assert lp["notes_diff"] == "was: - yelp fact one\nnow: - yelp fact two"
    assert (
        lp["section"] == "sources"
        and "now: Check the union covers every key." in lp["section_diff"]
    )


def test_no_past_answer_and_no_literal_guard_text_reaches_the_history(
    lineage: tuple[Path, Path],
) -> None:
    h = _history(lineage)
    text = json.dumps(h) + "".join(hist.question_block(h, q) for q in h["questions"])
    text += hist.attempt_block(h, "yelp") + hist.attempt_block(h, "playbook:sources")
    assert SECRET not in text  # H1: agnews/1 passed under a_sql with this answer
    assert "Philadelphia" not in text  # a literal-guard refusal is shown by kind only
    refusals = h["attempts"][0]["sessions"][0]["refusals"]
    assert refusals == ["gold values written literally", "G1 decisive for yelp/1: the city"]


def test_the_blocks_a_session_reads_and_their_caps(tmp_path: Path) -> None:
    h = hist.build(hist.FolderSource(*_lineage(tmp_path, long_notes=True)), "c_sql")
    block = hist.question_block(h, "yelp/1")
    assert block.startswith("History of yelp/1") and "Last passed under b_sql" in block
    assert "c_sql ★ (opus): answer FAIL · SQL FAIL; breaks at sources" in block
    assert len(h["questions"]["yelp/1"]["last_passed"]["notes_diff"]) <= hist.DIFF_MAX + 1  # H4
    step = hist.attempt_block(h, "playbook:sources")
    assert "A new sources rule." in step and "SQL lost here" in step and "patents/2" in step
    ds = hist.attempt_block(h, "yelp")
    assert "had nothing accepted (c_sql's text kept)" in ds and "SQL gained here: yelp/2." in ds
    assert len(step) <= hist.ATTEMPT_MAX and "no session for patents" in hist.attempt_block(
        h, "patents"
    )


# ── the MLflow side (D42 A): the same history from a stand-in client ─────────


class _FakeMlflow:
    """Serves the tmp folders the way the central MLflow serves their copies: eval runs with
    run.json, scorecard.json, results.jsonl and agent/; round runs with optimise.json and the
    outcome.json `dab promote` logs."""

    def __init__(self, runs: Path, agents: Path) -> None:
        self.files: dict[str, Path] = {}
        self.eval, self.opt = [], []
        for i, d in enumerate(sorted(runs.iterdir())):
            rid = f"e{i}"
            self.files[rid] = d
            self.eval.append(
                self._run(rid, i, {"mlflow.runName": d.name, "agent": d.name.removeprefix("run_")})
            )
        for i, (rec, out) in enumerate(outcome.all_outcomes(agents, runs)):
            rid = f"o{i}"
            d = runs.parent / "mlflow" / rid
            d.mkdir(parents=True)
            shutil.copy(agents / rec["version"] / "optimise.json", d / "optimise.json")
            (d / "outcome.json").write_text(json.dumps(out))
            self.files[rid] = d
            self.opt.append(self._run(rid, i, {"agent": rec["version"]}))

    @staticmethod
    def _run(rid: str, t: int, tags: dict[str, str]) -> Any:
        return SimpleNamespace(
            info=SimpleNamespace(run_id=rid, start_time=t), data=SimpleNamespace(tags=tags)
        )

    def search_runs(
        self, experiment_ids: list[str], filter_string: str, max_results: int
    ) -> list[Any]:
        return self.eval if "'eval'" in filter_string else self.opt

    def download_artifacts(self, run_id: str, path: str, dst: str) -> str:
        src = self.files[run_id] / path
        if src.is_dir():
            shutil.copytree(src, Path(dst) / path)
        elif src.exists():
            shutil.copy(src, Path(dst) / path)
        else:
            raise OSError(path)
        return str(Path(dst) / path)


def test_mlflow_and_the_folders_give_the_same_history(lineage: tuple[Path, Path]) -> None:
    from_mlflow = hist.build(
        hist.MlflowSource(client=_FakeMlflow(*lineage), experiment_id="1"), "c_sql"
    )
    assert from_mlflow["source"] == "mlflow"
    assert hist.parity(from_mlflow, _history(lineage)) == []


# ── the champion lock (B1) and the briefings (B5) ────────────────────────────


def test_a_round_from_a_run_that_is_not_the_champions_is_refused(
    lineage: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, agents = lineage
    monkeypatch.setattr(op, "RUNS_DIR", runs)
    champion = tmp_path / "champion"
    champion.write_text("c_sql\n")
    monkeypatch.setattr(versions, "CHAMPION_FILE", champion)
    with pytest.raises(op.NotChampionError, match="c_sql"):
        asyncio.run(op.optimise("run_d_sql", "e_sql"))


def test_a_component_briefing_carries_the_history_only_when_given(
    lineage: tuple[Path, Path],
) -> None:
    h = _history(lineage)
    rows = [{"query_id": "yelp/1", "answer": False, "detail": "rows differ", "result_diff": []}]
    results = {"yelp/1": {"question": "Which city?", "agent_sql": "select 1"}}
    args = ("sources", rows, results, {}, "system", "current", 600)
    with_h = op.component_briefing(*args, history=h)
    assert "Earlier rounds from this champion that lost to it" in with_h
    assert "History of yelp/1" in with_h and "Last passed under b_sql" in with_h
    assert "History of" not in op.component_briefing(*args)
