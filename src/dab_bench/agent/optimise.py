"""`dab optimise <run> --into <version>`: one round of the optimisation loop (plan s06, B9; s08).

Round 2 onward (plan s08, D32 B) the round has two kinds of session, run in parallel:

- **Component sessions** write the SQL **playbook** in `system.md`: seven headed sections,
  one per step of a statement (sources, keys, parse, filter, metric, rank, shape; the
  ledger's components, `eval/ledger.py`). One session per step at which at least one failed
  training question's statement first breaks, across every dataset: it reads those
  questions with the ledger's words for both statements, both statements and the result
  diff, and writes that step's section (tool `write_section`, the same guard, at most 600
  characters; `system.md` stays under 8,000). The run must have a ledger
  (`dab diagnose --ledger`). The playbook's skeleton (`agents/optimiser/playbook.md`) is
  inserted into `system.md` the first time, and it asks for the plan first, so the new
  version's `agent.yaml` gets `plan: true` (D34).
- **Dataset sessions**, as in round 1, write the dataset notes, now led by the ledger's
  lines and capped at 2,000 characters.

The cross-dataset `system.md` pass of round 1 is not run: the component sessions are the
generalisation.

From s11 (D38, D40 B), a round may read **every error** of the 54 (`train_all`, `dab optimise
--train all`): the held-out split is not applied, and wrong answers without a golden reach
their dataset session with the question, the agent's answer and the validator's fail (no
reference statement exists for them). With `strict`, four guards join the literal one: G1, an
Opus reviewer per write (`eval/review.py`); G2, every gold value searched in the finished
text, a hit reverting that unit to the parent's (`guards.audit`); G3, a playbook section only
for a step where two or more errors break, its rationale citing two of them by id; G4, no
text naming a question. `dab crossfit` runs the same round per fold with that fold's
questions excluded (`exclude`) to score each question with a prompt that never read it.

From s13 (D42–D45) a round starts from the **champion's run** (`from_champion`; `dab optimise`
with no run picks it, and a run of any other version is refused), and with `history` each
session also reads what came before that run (`eval/history.py`, built from MLflow and written
to `runs/<run>/history.json`): every failed question's answer and SQL under each version, what
each round changed and which flips had no prompt change behind them, the statement that last
passed a regressed question, and every round from the champion that lost to it — what it
wrote, what was refused, and what it gained and lost. The history is input only: what a
session writes passes the same guards. Each session is also logged as an MLflow trace
(`kind=optimise_session`). Round 1's own description follows.

The optimiser is an agent (`agents/optimiser/`, Sonnet 5 at medium effort) that turns a
scored run's failures into **dataset notes**, the per-dataset block the eval agent's
prompt carries under "Notes for this dataset" (`agents/<version>/datasets/<ds>.md`).

- One session per dataset with at least one failed training question (any of answer,
  SQL or decision failed), in parallel. A session sees what the agent saw for that
  dataset (its composed prompt), each failed train question with its scorecard,
  category, agent SQL beside golden SQL, result diff and trace summary, and the SQL of
  the train questions that passed. Never a held-out question, another dataset's
  questions, or a question without a golden (D29).
- It has two tools: `query_db` (read-only, as `dab_agent`) to check a claim against the
  data, and `write_notes(notes, rationale)`. Every write is checked (`eval/guards.py`: no
  question text, no gold value, no golden SQL fragment, at most 1,500 characters); a
  refused write is sent back with the reasons; a second *leak* refusal drops the notes (a
  length overrun alone is a format fix and does not count toward the drop).
- Then one cross-dataset pass (D31 A) may move a recurring lesson into `system.md`,
  under the same guards (3,000 characters).
- Each session runs isolated exactly like a trial: an empty working directory, no
  CLAUDE.md or memory, a strict MCP config, the CLI's init message checked.

The new version is a copy of the source with the notes (and any new `system.md`), its
`agent.yaml` naming `challenger_of`. `agents/<version>/optimise.json` records the round:
the source run, the split, every session's notes, rationale, refusals, cost and turns.
It is not a prompt surface, so it is outside the fingerprint. Session traces go to
`runs/<run>/optimise/<version>/`.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    UserMessage,
    create_sdk_mcp_server,
    tool,
)

from dab_bench.agent.isolation import (
    SESSION_SETTINGS,
    IsolationError,
    check_init,
    init_record,
    isolated_cwd,
)
from dab_bench.agent.llm import EFFORT, require_live, resolve_model, subscription_env
from dab_bench.agent.prompt import load_context
from dab_bench.agent.session import _block_to_dict
from dab_bench.agent.tools import ToolState, call_tool
from dab_bench.agent.versions import AgentVersion, load_version
from dab_bench.config import AGENTS_DIR, RUNS_DIR
from dab_bench.eval.guards import NOTES_MAX_CHARS, Guard, load_guard

OPTIMISER_DIR = AGENTS_DIR / "optimiser"
SYSTEM_MAX_CHARS = 3_000  # round 1's cross-dataset pass
# s08: system.md with the playbook: room for all seven sections at SECTION_MAX on top of the
# instructions (round 2 first ran at 5,000, which left 282 characters a section)
PLAYBOOK_SYSTEM_MAX = 8_000
SECTION_MAX = 600  # s08: one playbook section, at most
NOTES_CAP = 2_000  # s08: dataset notes (round 1: 1,500; the cap did most of the refusing)
SYSTEM_PASS_TURNS = 6
DIFF_LINES = 40
TOOLS = ["mcp__dab__query_db", "mcp__dab__write_notes"]
PLAYBOOK_HEAD = "## From the question to the statement"


class NotChampionError(ValueError):
    """A round was asked to start from a run that is not the champion's (s13)."""


_SECTION = re.compile(r"^### (\d) · (\w+) — .*$", re.M)


@dataclass
class Session:
    scope: str  # a dataset, "system.md" (round 1's pass) or "playbook:<component>" (s08)
    kind: str = "dataset"  # dataset | component | system
    notes: str | None = None  # accepted text; None when nothing was accepted
    rationale: str = ""
    refusals: list[dict[str, Any]] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)  # the failed train questions it saw
    n_turns: int = 0
    duration_ms: int = 0
    cost_usd: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    dropped: bool = False  # a second leak refusal: nothing more is accepted
    reviews: list[dict[str, Any]] = field(default_factory=list)  # G1 verdicts, per write (s11)
    budget: int | None = None  # the character cap this session wrote under
    # every write, in order: {"ok", "chars", "problems"} (no text: a refused one may leak)
    attempts: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)


# ── what one session reads ─────────────────────────────────────────────────


def _mark(v: bool | None) -> str:
    return "—" if v is None else "pass" if v else "fail"


def _trace_summary(trace: dict[str, Any]) -> str:
    calls = trace.get("tool_calls") or []
    errs = sum(1 for c in calls if c.get("error"))
    names: dict[str, int] = {}
    for c in calls:
        names[c["tool"]] = names.get(c["tool"], 0) + 1
    tools = ", ".join(f"{k} ×{v}" for k, v in names.items()) or "none"
    return (
        f"{trace.get('n_turns', 0)} turns; tools {tools}; {errs} tool error(s); "
        f"ended {trace.get('terminal_reason') or '—'}"
    )


def briefing(
    dataset: str,
    version: AgentVersion,
    card: dict[str, Any],
    results: dict[str, dict[str, Any]],
    traces: dict[str, dict[str, Any]],
    goldens: dict[str, dict[str, Any]],
    train: set[str],
    no_golden: bool = False,
    history: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    """The user message of one dataset's session, and the failed questions it covers.
    `no_golden` (s11, every error read): wrong answers without a golden are included.
    `history` (s13): each failed question's history, and the rounds from the champion that
    lost (`eval/history.py`)."""
    from dab_bench.eval import history as hist

    ctx = load_context(dataset)
    rows = [q for q in card["questions"] if q["query_id"].split("/")[0] == dataset]
    rows = [
        q
        for q in rows
        if q.get("trial", 1) == 1
        and q["query_id"] in train
        and (q["golden_id"] is not None or no_golden)
    ]
    failed = [q for q in rows if False in (q["answer"], q["sql"], q["decision"])]
    passed = [q for q in rows if q not in failed]
    which = "" if no_golden else "training "
    parts = [
        f"# Dataset {dataset}",
        "## The prompt the agent saw for this dataset\n\n````\n"
        + version.prompt_for(ctx)
        + "\n````",
        *(
            [
                "## Earlier rounds from this champion that lost to it\n\n"
                + hist.attempt_block(history, dataset)
            ]
            if history and history.get("attempts")
            else []
        ),
        f"## Failed {which}questions ({len(failed)})",
    ]
    for q in failed:
        qid = q["query_id"]
        r, t, g = results[qid], traces.get(qid, {}), goldens.get(qid, {})
        if q["golden_id"] is None:
            parts.append(
                "\n".join(
                    [
                        f"### {qid} · wrong answer, no reference statement",
                        f"Question: {r['question']}",
                        "Scorecard: answer fail. No reference statement exists for this "
                        "question; the validator says only that the answer is wrong.",
                        f"Agent mode: {r.get('mode') or '—'}; step: {r.get('step') or '—'}",
                        f"Trace: {_trace_summary(t)}",
                        "Agent SQL:\n```sql\n"
                        + (r.get("agent_sql") or "(none submitted)")
                        + "\n```",
                        "Agent answer (wrong):\n```\n" + str(r.get("answer") or "")[:600] + "\n```",
                        *([hist.question_block(history, qid)] if history else []),
                    ]
                )
            )
            continue
        diff = "\n".join(
            ("  " if d["op"] == "eq" else "- " if d["op"] == "del" else "+ ") + d["text"]
            for d in (q.get("result_diff") or [])[:DIFF_LINES]
        )
        structure = "; ".join(
            f"{k}: golden {v.get('golden')!r} vs agent {v.get('agent')!r}"
            for k, v in (q.get("structure") or {}).items()
            if isinstance(v, dict)
        )
        led = ledger_lines(q)
        parts.append(
            "\n".join(
                [
                    f"### {qid} · {q['category']}",
                    f"Question: {r['question']}",
                    f"Scorecard: answer {_mark(q['answer'])} · SQL {_mark(q['sql'])} · "
                    f"decision {_mark(q['decision'])}. {q['detail']}",
                    f"Golden kind: {g.get('kind', '—')} (the right mode is "
                    f"{'derived' if g.get('kind') == 'evidence' else 'pass_through'}). "
                    f"Agent mode: {r.get('mode') or '—'}; step: {r.get('step') or '—'}",
                    f"Validator: {r.get('reason', '')[:300]}",
                    *([led] if led else []),
                    *([f"Structure differences: {structure}"] if structure and not led else []),
                    f"Trace: {_trace_summary(t)}",
                    "Agent SQL:\n```sql\n" + (r.get("agent_sql") or "(none submitted)") + "\n```",
                    "Golden SQL:\n```sql\n" + (g.get("sql") or "") + "\n```",
                    *(
                        [
                            "Result diff (- golden rows, + agent rows, first "
                            f"{DIFF_LINES} lines):\n```\n{diff}\n```"
                        ]
                        if diff
                        else []
                    ),
                    *([hist.question_block(history, qid)] if history else []),
                ]
            )
        )
    got_right = "Training questions" if which else "Questions"
    parts.append(f"## {got_right} the agent got right ({len(passed)})")
    for q in passed:
        r = results[q["query_id"]]
        parts.append(
            f"### {q['query_id']}\nQuestion: {r['question']}\n```sql\n{r.get('agent_sql') or ''}\n```"
        )
    return "\n\n".join(parts) + "\n", [q["query_id"] for q in failed]


def ledger_lines(q: dict[str, Any], only: str | None = None) -> str:
    """A scorecard row's ledger as the optimiser reads it: where the statement breaks and, per
    step, what the reference and the agent do (every step, or `only` one, plus the others that
    differ)."""
    from dab_bench.eval.ledger import COMPONENTS

    led = q.get("ledger") or {}
    g, a, v = led.get("golden") or {}, led.get("agent"), led.get("verdicts") or {}
    if not g or not a:
        return ""
    steps = [c for c in COMPONENTS if c == only or v.get(c) == "differs"] if only else COMPONENTS
    lines = [
        f"Where the statement breaks (the ledger): {led.get('breaks_at') or 'no single step'}"
        + (f" — {led['why']}" if led.get("why") else "")
    ]
    for c in steps:
        mark = "differs" if v.get(c) == "differs" else v.get(c, "same")
        lines.append(f"- {c} ({mark}): reference: {g.get(c, 'none')} | agent: {a.get(c, 'none')}")
    return "\n".join(lines)


def component_briefing(
    component: str,
    rows: list[dict[str, Any]],
    results: dict[str, dict[str, Any]],
    goldens: dict[str, dict[str, Any]],
    system_md: str,
    current: str,
    budget: int,
    cite: bool = False,
    history: dict[str, Any] | None = None,
) -> str:
    """The user message of one component session: every failed train question, across
    datasets, whose statement first breaks at `component`. `cite` (s11 G3): the rationale must
    name two or more of them by id."""
    from dab_bench.eval import history as hist
    from dab_bench.eval.ledger import WHAT

    parts = [
        f"# Step: {component} — {WHAT[component]}",
        f"Your budget: at most {budget:,} characters for the section.",
        *(
            [
                "Generalise: the section must hold for two or more of the questions below. In "
                "your rationale, cite by id (such as yelp/2) at least two of them that each rule "
                "comes from. Never name a question in the section itself."
            ]
            if cite
            else []
        ),
        "## The current section\n\n" + (current.strip() or "(empty)"),
        "## The shared instructions the agent reads (system.md), for context\n\n````\n"
        + system_md
        + "\n````",
        *(
            [
                "## Earlier rounds from this champion that lost to it\n\n"
                + hist.attempt_block(history, f"playbook:{component}")
            ]
            if history and history.get("attempts")
            else []
        ),
        f"## Failed training questions whose statement first breaks at {component} ({len(rows)})",
    ]
    for q in rows:
        qid = q["query_id"]
        r, g = results[qid], goldens.get(qid, {})
        diff = "\n".join(
            ("  " if d["op"] == "eq" else "- " if d["op"] == "del" else "+ ") + d["text"]
            for d in (q.get("result_diff") or [])[:20]
        )
        parts.append(
            "\n".join(
                [
                    f"### {qid} (dataset {qid.split('/')[0]})",
                    f"Question: {r['question']}",
                    f"Result: {q.get('sql_detail') or q.get('detail') or ''}. Answer "
                    f"{_mark(q['answer'])}.",
                    ledger_lines(q, only=component),
                    "Agent SQL:\n```sql\n" + (r.get("agent_sql") or "") + "\n```",
                    "Reference SQL:\n```sql\n" + (g.get("sql") or "") + "\n```",
                    *(
                        [f"Result diff (- reference rows, + agent rows):\n```\n{diff}\n```"]
                        if diff
                        else []
                    ),
                    *([hist.question_block(history, qid)] if history else []),
                ]
            )
        )
    return "\n\n".join(parts) + "\n"


# ── the playbook in system.md (s08) ─────────────────────────────────────────


def with_playbook(system_md: str) -> str:
    """`system_md` with the playbook skeleton appended, unless it has one already."""
    if PLAYBOOK_HEAD in system_md:
        return system_md
    return system_md.rstrip() + "\n\n" + (OPTIMISER_DIR / "playbook.md").read_text().strip() + "\n"


def sections(system_md: str) -> dict[str, str]:
    """The playbook's section bodies by component (empty when a section has none)."""
    heads = list(_SECTION.finditer(system_md))
    out = {}
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(system_md)
        out[m.group(2)] = system_md[m.end() : end].strip()
    return out


def fill_sections(system_md: str, bodies: dict[str, str]) -> str:
    """Replace the named sections' bodies; every other section keeps its own."""
    heads = list(_SECTION.finditer(system_md))
    if not heads:
        return system_md
    out = [system_md[: heads[0].start()]]
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(system_md)
        body = bodies.get(m.group(2), system_md[m.end() : end].strip())
        out.append(m.group(0) + "\n\n" + (body.strip() + "\n\n" if body.strip() else ""))
    return "".join(out).rstrip() + "\n"


def section_budget(system_md: str, components: list[str]) -> int:
    """Characters each of `components`' sections may use so system.md stays under the cap."""
    empty = fill_sections(system_md, dict.fromkeys(components, ""))
    free = PLAYBOOK_SYSTEM_MAX - len(empty) - 4 * len(components)
    return max(0, min(SECTION_MAX, free // max(1, len(components))))


def system_briefing(version: AgentVersion, card: dict[str, Any], notes: dict[str, str]) -> str:
    cats: dict[str, dict[str, int]] = {}
    for q in card["questions"]:
        if q["category"] in ("solved", "no golden"):
            continue
        ds = q["query_id"].split("/")[0]
        cats.setdefault(q["category"], {}).setdefault(ds, 0)
        cats[q["category"]][ds] += 1
    lines = [
        f"- {c}: " + ", ".join(f"{d} {n}" for d, n in sorted(by.items()))
        for c, by in sorted(cats.items(), key=lambda kv: -sum(kv[1].values()))
    ]
    return "\n\n".join(
        [
            "## Current system.md\n\n````\n" + version.system_prompt + "\n````",
            "## Failure categories across datasets (all scored questions)\n" + "\n".join(lines),
            "## New dataset notes\n"
            + "\n\n".join(f"### {ds}\n{text}" for ds, text in sorted(notes.items()) if text),
        ]
    )


# ── one session ────────────────────────────────────────────────────────────


def _server(
    state: ToolState,
    sess: Session,
    guard: Guard,
    dataset: str | None,
    tool_name: str = "write_notes",
    query: bool | None = None,
    reviewer: Any = None,
    cite_from: list[str] | None = None,
) -> Any:
    """`reviewer` (s11 G1): an async callable text -> (problems, record); `cite_from` (s11
    G3): the ids the rationale must cite two of."""

    @tool(
        "query_db",
        "Run read-only Postgres SQL (schema dataagentbench; tables <dataset>_<table>) as the agent's "
        "role. Returns up to `limit` rows (default 50, max 500).",
        {
            "type": "object",
            "properties": {"sql": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["sql"],
        },
    )
    async def query_db(args: dict[str, Any]) -> dict[str, Any]:
        out, err = await asyncio.to_thread(call_tool, state, "query_db", args)
        return {"content": [{"type": "text", "text": out}], **({"is_error": True} if err else {})}

    @tool(
        tool_name,
        "Finish: the complete text (it replaces the current one) and a short rationale.",
        {
            "type": "object",
            "properties": {"notes": {"type": "string"}, "rationale": {"type": "string"}},
            "required": ["notes", "rationale"],
        },
    )
    async def write_notes(args: dict[str, Any]) -> dict[str, Any]:
        notes = str(args.get("notes") or "").strip()
        rationale = str(args.get("rationale") or "").strip()
        if sess.dropped:
            return {
                "content": [{"type": "text", "text": "The notes were dropped. Stop."}],
                "is_error": True,
            }
        # the rationale is leak-checked but not length-capped: the cap is for the text that
        # enters a prompt (a 282-character section cap refused rationales in round 2, s08)
        rationale_problems = (
            guard.leaks(guard.check(rationale, prompt_text=False)) if rationale else []
        )
        problems = (guard.check(notes) if notes else []) + rationale_problems
        if not problems and notes and cite_from is not None:  # G3 (s11)
            cited = {
                q for q in cite_from if re.search(rf"(?<![\w/]){re.escape(q)}(?!\d)", rationale)
            }
            if len(cited) < min(2, len(cite_from)):
                problems.append(
                    "G3 cite, in the rationale, at least two of the questions you read (by id, "
                    "such as yelp/2) that the section generalises from"
                )
        if not problems and notes and reviewer is not None:  # G1 (s11): after the cheap checks
            g1, rec = await reviewer(notes)
            sess.reviews.append(rec)
            problems += g1
        sess.attempts.append({"ok": not problems, "chars": len(notes), "problems": problems})
        if problems:
            sess.refusals.append(
                {
                    "problems": problems,
                    "notes_chars": len(notes),
                    "rationale_chars": len(rationale),
                    "redacted": True,
                }
            )
            # a leak (question text, gold value, golden SQL) is sent back once, then the notes are
            # dropped; a length overrun alone is a format fix and does not count toward the drop
            leaks = sum(1 for r in sess.refusals if guard.leaks(r["problems"]))
            if guard.leaks(problems) and leaks >= 2:
                stored_rationale = "[redacted]" if guard.leaks(rationale_problems) else rationale
                sess.notes, sess.rationale, sess.dropped = None, stored_rationale, True
                text = "Refused again: " + "; ".join(problems) + ". The notes are dropped. Stop."
            else:
                text = "Refused: " + "; ".join(problems) + ". Fix exactly this and call again."
            return {"content": [{"type": "text", "text": text}], "is_error": True}
        sess.notes, sess.rationale = notes, rationale
        return {"content": [{"type": "text", "text": "Accepted. Stop now."}]}

    query = dataset is not None if query is None else query
    tools = [query_db, write_notes] if query else [write_notes]
    return create_sdk_mcp_server(name="dab", version="1.0.0", tools=tools)


async def run_session(
    scope: str,
    system_prompt: str,
    message: str,
    guard: Guard,
    optimiser: AgentVersion,
    dataset: str | None,
    kind: str = "dataset",
    tool_name: str = "write_notes",
    query: bool | None = None,
    reviewer: Any = None,
    cite_from: list[str] | None = None,
) -> Session:
    require_live()
    cfg = optimiser.config
    query = dataset is not None if query is None else query
    sess = Session(scope=scope, kind=kind, budget=guard.max_chars)
    # the cross-dataset pass has no query_db, so its state's dataset is never read
    state = ToolState(
        dataset=dataset or "",
        ctx=load_context(dataset or "yelp"),
        trial_key=f"optimise_{scope}",
        sandbox=None,
    )
    allowed = (["mcp__dab__query_db"] if query else []) + [f"mcp__dab__{tool_name}"]
    cwd = isolated_cwd()
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=resolve_model(cfg.model),
        tools=[],
        allowed_tools=allowed,
        mcp_servers={
            "dab": _server(state, sess, guard, dataset, tool_name, query, reviewer, cite_from)
        },
        strict_mcp_config=True,
        permission_mode="bypassPermissions",
        max_turns=cfg.max_turns if query else SYSTEM_PASS_TURNS,
        cwd=str(cwd),
        env=subscription_env(),
        setting_sources=[],
        settings=SESSION_SETTINGS,
        effort=cfg.effort or EFFORT,  # type: ignore[arg-type]
    )
    sess.trace.append({"role": "system", "content": system_prompt})
    sess.trace.append({"role": "user", "content": message})
    t0 = time.time()

    async def _run() -> None:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(message)
            async for msg in client.receive_response():
                if isinstance(msg, SystemMessage) and msg.subtype == "init":
                    sess.trace.append({"role": "init", "content": init_record(msg.data)})
                    problems = check_init(msg.data, allowed, cwd)
                    if problems:
                        raise IsolationError("; ".join(problems))
                elif isinstance(msg, AssistantMessage):
                    sess.trace.append(
                        {
                            "role": "assistant",
                            "t": round(time.time() - t0, 3),
                            "content": [_block_to_dict(b) for b in msg.content],
                        }
                    )
                elif isinstance(msg, UserMessage) and not isinstance(msg.content, str):
                    sess.trace.append(
                        {
                            "role": "tool",
                            "t": round(time.time() - t0, 3),
                            "content": [_block_to_dict(b) for b in msg.content],
                        }
                    )
                elif isinstance(msg, ResultMessage):
                    sess.n_turns = msg.num_turns
                    sess.cost_usd = msg.total_cost_usd
                    u = msg.usage or {}
                    sess.input_tokens = (
                        int(u.get("input_tokens", 0))
                        + int(u.get("cache_read_input_tokens", 0))
                        + int(u.get("cache_creation_input_tokens", 0))
                    )
                    sess.output_tokens = int(u.get("output_tokens", 0))
                    if msg.is_error:
                        sess.error = f"{msg.subtype}: {(msg.errors or [msg.result or ''])[0]}"[:500]

    try:
        await asyncio.wait_for(_run(), timeout=cfg.timeout_s)
    except IsolationError:
        raise
    except TimeoutError:
        sess.error = f"timeout after {cfg.timeout_s}s"
    except Exception as e:  # noqa: BLE001 - recorded; the other datasets carry on
        sess.error = f"{type(e).__name__}: {e}"[:500]
    sess.duration_ms = int((time.time() - t0) * 1000)
    sess.trace.append({"role": "tools", "content": state.calls})
    return sess


# ── the round ──────────────────────────────────────────────────────────────


def _read_run(run_id: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    run_dir = RUNS_DIR / run_id
    meta = json.loads((run_dir / "run.json").read_text())
    results = {}
    traces = {}
    for line in (run_dir / "results.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r["trial"] != 1:
            continue
        results[r["query_id"]] = r
        tp = run_dir / (r.get("trace_file") or "")
        if r.get("trace_file") and tp.exists():
            traces[r["query_id"]] = json.loads(tp.read_text())
    return meta, results, traces


def failed_train(
    card: dict[str, Any], train: set[str], no_golden: bool = False
) -> list[dict[str, Any]]:
    """Trial-1 rows of training questions with a golden that failed any of the three checks;
    with `no_golden` (s11, every error read) also wrong answers without a golden."""
    return [
        q
        for q in card["questions"]
        if q["trial"] == 1
        and q["query_id"] in train
        and (q["golden_id"] is not None or no_golden)
        and False in (q["answer"], q["sql"], q["decision"])
    ]


def by_component(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Failed rows grouped by the step their statement first breaks at (the ledger's)."""
    from dab_bench.eval.ledger import COMPONENTS

    out: dict[str, list[dict[str, Any]]] = {}
    for q in rows:
        b = q.get("breaks_at")
        if b in COMPONENTS and (q.get("ledger") or {}).get("agent"):
            out.setdefault(b, []).append(q)
    return {c: out[c] for c in COMPONENTS if c in out}


def breadth(
    groups: dict[str, list[dict[str, Any]]], least: int = 2
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    """G3 (s11): (the steps that get a playbook session, the ids of those that do not). A step
    where fewer than `least` errors break writes no section; its questions still reach their
    dataset sessions."""
    kept = {c: rows for c, rows in groups.items() if len(rows) >= least}
    skipped = {c: [q["query_id"] for q in rows] for c, rows in groups.items() if len(rows) < least}
    return kept, skipped


async def optimise(
    run_id: str,
    into: str,
    workers: int = 4,
    components: bool = True,
    model: str | None = None,
    train_all: bool = False,
    exclude: set[str] | None = None,
    strict: bool = False,
    crossfit: dict[str, Any] | None = None,
    from_champion: bool = True,
    history: bool = False,
) -> dict[str, Any]:
    """One round. `components` (s08, D32 B): component sessions write the playbook and
    dataset sessions the notes; without it, round 1's per-dataset sessions and system pass.
    `model` overrides the optimiser's agent.yaml for this round (recorded in optimise.json).
    s11: `train_all` reads every error of the 54; `exclude` holds questions out (a cross-fit
    fold); `strict` adds guards G1–G4; `crossfit` marks the version a fold (never listed).
    s13: `from_champion` refuses a run of any version but the champion; `history` builds the
    history from MLflow and gives it to every session."""
    from dab_bench.eval import golden
    from dab_bench.eval.scorecard import load_optimise_split, load_scorecard, score_run

    target = AGENTS_DIR / into
    if target.exists():
        raise FileExistsError(f"{target} exists; a version is never overwritten")
    split = load_optimise_split()
    if split is None and not train_all:
        raise FileNotFoundError("no train/held-out split: run `dab split-optimise` first")
    meta, results, traces = _read_run(run_id)
    if from_champion:
        from dab_bench.agent.versions import champion_name
        from dab_bench.eval.promote import champion_run

        champ = champion_name()
        if meta["agent"] != champ:
            raise NotChampionError(
                f"{run_id} is a run of {meta['agent']}; a round starts from the champion's run "
                f"({champ}): `dab optimise --into {into}` picks it (s13)"
            )
        champ_run_id = champion_run()
        if champ_run_id is not None and run_id != champ_run_id:
            raise NotChampionError(
                f"{run_id} is not {champ}'s newest complete run ({champ_run_id}): "
                f"`dab optimise --into {into}` picks it (s13)"
            )
    source = load_version(meta["agent"])
    if not source.submits_sql:
        raise ValueError(f"{source.name} has no submit_answer: nothing for the optimiser to read")
    card = load_scorecard(run_id) or score_run(run_id)
    everyone = {q["query_id"] for q in card["questions"] if q["trial"] == 1}
    held = set(exclude or ())
    train = (everyone if train_all else set((split or {}).get("train", []))) - held
    failed = failed_train(card, train, no_golden=train_all)
    groups = by_component(failed) if components else {}
    skipped: dict[str, list[str]] = {}
    if strict:
        groups, skipped = breadth(groups)
    if components and not groups:
        raise ValueError(
            f"no failed training question of {run_id} has a ledger: run "
            f"`dab diagnose {run_id} --ledger` first"
        )
    goldens = golden.current()
    past: dict[str, Any] | None = None
    history_rec: dict[str, Any] | None = None
    if history:  # s13 (D42 A): read from MLflow; a round without it does not start
        from dab_bench.eval import history as hist

        past = hist.build(hist.MlflowSource(), champion=meta["agent"])
        if past["champion_run"] != run_id:
            raise ValueError(
                f"MLflow's newest complete run of {meta['agent']} is {past['champion_run']}, "
                f"not {run_id}: optimise that run, or log this one (`dab runs log {run_id}`)"
            )
        hpath = hist.write(past)
        history_rec = {
            "file": str(hpath.relative_to(RUNS_DIR.parent)),
            "source": past["source"],
            "versions": [v["version"] for v in past["versions"]],
            "attempts": [a["version"] for a in past["attempts"]],
            "regressed": sorted(
                q for q, x in past["questions"].items() if x["status"] == "regressed"
            ),
        }
    optimiser = load_version(OPTIMISER_DIR.name)
    if model:
        optimiser = replace(optimiser, config=replace(optimiser.config, model=model))
    notes_cap = NOTES_CAP if components else NOTES_MAX_CHARS
    guard = load_guard(notes_cap, routing=strict)
    reviews_model = resolve_model(model) if model else None

    def reviewer_for(kind: str, dataset: str | None) -> Any:
        if not strict:
            return None
        from dab_bench.eval.review import review

        async def _r(text: str) -> tuple[list[str], dict[str, Any]]:
            return await review(text, kind, dataset, model=reviews_model)

        return _r

    datasets = sorted({q["query_id"].split("/")[0] for q in failed})
    sem = asyncio.Semaphore(max(1, workers))
    started = datetime.now(UTC).isoformat()
    system_md = with_playbook(source.system_prompt) if components else source.system_prompt
    current = sections(system_md)
    budget = section_budget(system_md, list(groups))
    component_prompt = (OPTIMISER_DIR / "component.md").read_text()

    async def one(ds: str) -> Session:
        message, qs = briefing(
            ds, source, card, results, traces, goldens, train, train_all, history=past
        )
        async with sem:
            s = await run_session(
                ds,
                optimiser.system_prompt,
                message,
                guard,
                optimiser,
                ds,
                reviewer=reviewer_for("dataset", ds),
            )
        s.questions = qs
        return s

    async def section(comp: str, rows: list[dict[str, Any]]) -> Session:
        message = component_briefing(
            comp,
            rows,
            results,
            goldens,
            system_md,
            current.get(comp, ""),
            budget,
            cite=strict,
            history=past,
        )
        g = replace(guard, max_chars=budget)
        async with sem:
            s = await run_session(
                f"playbook:{comp}",
                component_prompt,
                message,
                g,
                optimiser,
                None,
                kind="component",
                tool_name="write_section",
                query=True,
                reviewer=reviewer_for("component", None),
                cite_from=[q["query_id"] for q in rows] if strict else None,
            )
        s.questions = [q["query_id"] for q in rows]
        return s

    sessions = list(
        await asyncio.gather(
            *(section(c, rows) for c, rows in groups.items()), *(one(ds) for ds in datasets)
        )
    )
    notes = dict(source.notes)
    bodies: dict[str, str] = {}
    for s in sessions:
        if s.notes is None:
            continue
        if s.kind == "component":
            bodies[s.scope.removeprefix("playbook:")] = s.notes
        else:
            notes[s.scope] = s.notes
    if components:
        system_md = fill_sections(system_md, bodies)
    audit_hits: dict[str, int] = {}
    if strict:  # G2: every gold value in everything the optimiser wrote, inherited text included
        from dab_bench.eval.guards import audit

        units = {f"playbook:{c}": b for c, b in sections(system_md).items()}
        units |= {f"notes:{ds}": t for ds, t in notes.items()}
        audit_hits = audit(units, guard.golds)
        parent = sections(with_playbook(source.system_prompt)) if components else {}
        for unit in audit_hits:
            kind_, name = unit.split(":", 1)
            if kind_ == "playbook":
                keep = parent.get(name, "")
                keep = "" if audit({unit: keep}, guard.golds) else keep
                system_md = fill_sections(system_md, {name: keep})
            else:
                keep = source.notes.get(name, "")
                notes[name] = "" if audit({unit: keep}, guard.golds) else keep
    if not components:
        sys_guard = Guard(guard.questions, guard.golds, guard.golden_sqls, SYSTEM_MAX_CHARS)
        system_pass = await run_session(
            "system.md",
            (OPTIMISER_DIR / "system_pass.md").read_text(),
            system_briefing(source, card, {s.scope: s.notes or "" for s in sessions}),
            sys_guard,
            optimiser,
            None,
            kind="system",
        )
        if system_pass.notes:
            system_md = system_pass.notes.rstrip() + "\n"
        sessions.append(system_pass)

    # the new version: a copy, the notes, the lineage
    shutil.copytree(source.path, target, ignore=shutil.ignore_patterns("optimise.json"))
    cfg = yaml.safe_load((target / "agent.yaml").read_text()) or {}
    header = (source.path / "agent.yaml").read_text().split("\n")
    comments = [ln for ln in header if ln.startswith("#")]
    cfg["challenger_of"] = source.name
    cfg.pop("measured_against", None)  # a round's parent is challenger_of
    if crossfit:  # a fold: kept for its record, never listed or promoted (s11)
        cfg["crossfit_of"] = crossfit["of"]
        cfg["crossfit_fold"] = crossfit["fold"]
    plan_first = PLAYBOOK_HEAD in system_md
    if plan_first:
        cfg["plan"] = True  # the playbook asks for the plan first (D34)
    method = (
        "component sessions write the playbook, dataset sessions the notes (s08, D32 B)"
        if components
        else "dataset sessions + a cross-dataset system.md pass (s06, D31 A)"
    )
    if train_all:
        method += "; every error of the 54 read (s11, D38)"
    if strict:
        method += "; guards G1–G4 (s11, D40 B)"
    if history_rec:
        method += "; the history of every earlier round read (s13, D45 A)"
    (target / "agent.yaml").write_text(
        "\n".join(
            [f"# {into}: {source.name} after one optimisation round of run {run_id} ({method})"]
            + comments
        )
        + "\n"
        + yaml.safe_dump(cfg, sort_keys=False)
    )
    (target / "system.md").write_text(system_md)
    (target / "datasets").mkdir(exist_ok=True)
    for ds, text in sorted(notes.items()):
        if text:
            (target / "datasets" / f"{ds}.md").write_text(text.rstrip() + "\n")
    new = load_version(into)
    record = {
        "version": into,
        "challenger_of": source.name,
        "source_run": run_id,
        "source_fingerprint": source.fingerprint,
        "fingerprint": new.fingerprint,
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "method": method,
        "optimiser": {
            "model": resolve_model(optimiser.config.model),
            "effort": optimiser.config.effort,
        },
        "split": (
            {"train": len(train), "heldout": len(held)}
            if train_all
            else {k: len(v) for k, v in (split or {}).items()}
        ),
        "trained_on": "all" if train_all and not held else "crossfit" if held else "train",
        "source_scorecard": card["totals"],
        "caps": {
            "notes": notes_cap,
            "section": budget if components else None,
            "system_md": PLAYBOOK_SYSTEM_MAX if components else SYSTEM_MAX_CHARS,
        },
        "playbook": {c: [q["query_id"] for q in rows] for c, rows in groups.items()},
        "plan_first": plan_first,
        "guards": {
            "literal": True,
            "g1_review": strict,
            "g2_audit": strict,
            "g3_breadth": strict,
            "g4_routing": strict,
        },
        **({"playbook_skipped_g3": skipped} if skipped else {}),
        **({"audit_g2": {"units_with_gold": audit_hits}} if strict else {}),
        **({"crossfit": crossfit} if crossfit else {}),
        "from_champion": from_champion,
        **({"history": history_rec} if history_rec else {}),
        "reviews_cost_usd": sum(r.get("cost_usd") or 0.0 for x in sessions for r in x.reviews),
        "cost_usd": sum(s.cost_usd or 0.0 for s in sessions)
        + sum(r.get("cost_usd") or 0.0 for x in sessions for r in x.reviews),
        "sessions": [{k: v for k, v in asdict(s).items() if k != "trace"} for s in sessions],
        "system_md_changed": system_md != source.system_prompt,
    }
    (target / "optimise.json").write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n")
    tdir = RUNS_DIR / run_id / "optimise" / into
    tdir.mkdir(parents=True, exist_ok=True)
    for s in sessions:
        name = s.scope.replace(".", "_").replace(":", "_")
        (tdir / f"{name}.json").write_text(
            json.dumps(asdict(s), ensure_ascii=False, indent=1, default=str)
        )
    try:
        record["mlflow_run_id"] = _log(record, target, tdir)
        from dab_bench.tracking.prompts import register

        record["prompt_version"] = register(new)
        from dab_bench.tracking.tracing import log_round_sessions

        record["session_traces"] = log_round_sessions(record, tdir, force=True)  # s13 (B3)
        (target / "optimise.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=1) + "\n"
        )
    except Exception as e:  # noqa: BLE001 - the folder is the record
        record["mlflow_error"] = f"{type(e).__name__}: {e}"
    return record


async def rerun_system_pass(into: str) -> dict[str, Any]:
    """Run (again) only the cross-dataset system.md pass for a version a round already wrote:
    it reads the version's accepted notes and the source run's scorecard, and replaces the
    round's `system.md` session in optimise.json."""
    from dab_bench.eval.scorecard import load_scorecard

    target = AGENTS_DIR / into
    record: dict[str, Any] = json.loads((target / "optimise.json").read_text())
    source = load_version(record["challenger_of"])
    new = load_version(into)
    card = load_scorecard(record["source_run"])
    if card is None:
        raise FileNotFoundError(f"no scorecard for {record['source_run']}")
    optimiser = load_version(OPTIMISER_DIR.name)
    guard = load_guard(NOTES_MAX_CHARS)
    sys_guard = Guard(guard.questions, guard.golds, guard.golden_sqls, SYSTEM_MAX_CHARS)
    changed_notes = {
        s["scope"]: s["notes"] or "" for s in record["sessions"] if s["scope"] != "system.md"
    }
    s = await run_session(
        "system.md",
        (OPTIMISER_DIR / "system_pass.md").read_text(),
        system_briefing(source, card, changed_notes),
        sys_guard,
        optimiser,
        None,
        kind="system",
    )
    if s.notes:
        (target / "system.md").write_text(s.notes.rstrip() + "\n")
    new = load_version(into)
    entry = {k: v for k, v in asdict(s).items() if k != "trace"}
    # the pass it replaces stays on the record (it was paid for), outside `sessions`
    record.setdefault("superseded", []).extend(
        x for x in record["sessions"] if x["scope"] == "system.md"
    )
    record["sessions"] = [x for x in record["sessions"] if x["scope"] != "system.md"] + [entry]
    record["system_md_changed"] = new.system_prompt != source.system_prompt
    record["fingerprint"] = new.fingerprint
    record["cost_usd"] = sum(
        x.get("cost_usd") or 0.0 for x in record["sessions"] + record["superseded"]
    )
    record["system_pass_rerun_at"] = datetime.now(UTC).isoformat()
    tdir = RUNS_DIR / record["source_run"] / "optimise" / into
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "system_md.json").write_text(
        json.dumps(asdict(s), ensure_ascii=False, indent=1, default=str)
    )
    try:
        from dab_bench.tracking.prompts import register

        record["prompt_version"] = register(new)
    except Exception as e:  # noqa: BLE001 - the folder is the record
        record["mlflow_error"] = f"{type(e).__name__}: {e}"
    (target / "optimise.json").write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n")
    try:  # s13: the round's MLflow copy follows the record the history reads
        from dab_bench.eval.outcome import relog_record

        relog_record(record)
    except Exception as e:  # noqa: BLE001
        record["mlflow_error"] = f"{type(e).__name__}: {e}"
    return record


def _log(record: dict[str, Any], target: Path, tdir: Path) -> str:
    import mlflow

    from dab_bench.tracking.mlflow_log import _client_setup, _required_tags

    _client_setup()
    with mlflow.start_run(run_name=f"optimise-{record['version']}") as run:
        mlflow.set_tags(
            _required_tags()
            | {
                "kind": "optimise",
                "agent": record["version"],
                "challenger_of": record["challenger_of"],
                "source_run": record["source_run"],
                "fingerprint": record["fingerprint"],
                "model": record["optimiser"]["model"],
            }
        )
        sessions = record["sessions"]
        mlflow.log_metrics(
            {
                "cost_usd": float(record["cost_usd"]),
                "sessions": float(len(sessions)),
                "notes_accepted": float(sum(1 for s in sessions if s["notes"] is not None)),
                "refusals": float(sum(len(s["refusals"]) for s in sessions)),
                "system_md_changed": 1.0 if record["system_md_changed"] else 0.0,
            }
        )
        mlflow.log_artifact(str(target / "optimise.json"))
        mlflow.log_artifacts(str(target / "datasets"), artifact_path="datasets")
        mlflow.log_artifact(str(target / "system.md"))
        mlflow.log_artifacts(str(tdir), artifact_path="sessions")
        return str(run.info.run_id)
