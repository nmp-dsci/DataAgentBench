"""`dab optimise <run> --into <version>`: one round of the optimisation loop (plan s06, B9).

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
import shutil
import time
from dataclasses import asdict, dataclass, field
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
SYSTEM_MAX_CHARS = 3_000
SYSTEM_PASS_TURNS = 6
DIFF_LINES = 40
TOOLS = ["mcp__dab__query_db", "mcp__dab__write_notes"]


@dataclass
class Session:
    scope: str  # a dataset, or "system.md" for the cross-dataset pass
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
) -> tuple[str, list[str]]:
    """The user message of one dataset's session, and the failed questions it covers."""
    ctx = load_context(dataset)
    rows = [q for q in card["questions"] if q["query_id"].split("/")[0] == dataset]
    rows = [q for q in rows if q["query_id"] in train and q["golden_id"] is not None]
    failed = [q for q in rows if False in (q["answer"], q["sql"], q["decision"])]
    passed = [q for q in rows if q not in failed]
    parts = [
        f"# Dataset {dataset}",
        "## The prompt the agent saw for this dataset\n\n````\n"
        + version.prompt_for(ctx)
        + "\n````",
        f"## Failed training questions ({len(failed)})",
    ]
    for q in failed:
        qid = q["query_id"]
        r, t, g = results[qid], traces.get(qid, {}), goldens.get(qid, {})
        diff = "\n".join(
            ("  " if d["op"] == "eq" else "- " if d["op"] == "del" else "+ ") + d["text"]
            for d in (q.get("result_diff") or [])[:DIFF_LINES]
        )
        structure = "; ".join(
            f"{k}: golden {v.get('golden')!r} vs agent {v.get('agent')!r}"
            for k, v in (q.get("structure") or {}).items()
            if isinstance(v, dict)
        )
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
                    *([f"Structure differences: {structure}"] if structure else []),
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
                ]
            )
        )
    parts.append(f"## Training questions the agent got right ({len(passed)})")
    for q in passed:
        r = results[q["query_id"]]
        parts.append(
            f"### {q['query_id']}\nQuestion: {r['question']}\n```sql\n{r.get('agent_sql') or ''}\n```"
        )
    return "\n\n".join(parts) + "\n", [q["query_id"] for q in failed]


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


def _server(state: ToolState, sess: Session, guard: Guard, dataset: str | None) -> Any:
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
        "write_notes",
        "Finish: the complete notes (they replace the current ones) and a short rationale.",
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
        problems = guard.check(notes) if notes else []
        if problems:
            sess.refusals.append({"notes": notes, "problems": problems})
            # a leak (question text, gold value, golden SQL) is sent back once, then the notes are
            # dropped; a length overrun alone is a format fix and does not count toward the drop
            leaks = sum(1 for r in sess.refusals if guard.leaks(r["problems"]))
            if guard.leaks(problems) and leaks >= 2:
                sess.notes, sess.rationale, sess.dropped = None, rationale, True
                text = "Refused again: " + "; ".join(problems) + ". The notes are dropped. Stop."
            else:
                text = "Refused: " + "; ".join(problems) + ". Fix exactly this and call again."
            return {"content": [{"type": "text", "text": text}], "is_error": True}
        sess.notes, sess.rationale = notes, rationale
        return {"content": [{"type": "text", "text": "Accepted. Stop now."}]}

    tools = [write_notes] if dataset is None else [query_db, write_notes]
    return create_sdk_mcp_server(name="dab", version="1.0.0", tools=tools)


async def run_session(
    scope: str,
    system_prompt: str,
    message: str,
    guard: Guard,
    optimiser: AgentVersion,
    dataset: str | None,
) -> Session:
    require_live()
    cfg = optimiser.config
    sess = Session(scope=scope)
    # the cross-dataset pass has no query_db, so its state's dataset is never read
    state = ToolState(
        dataset=dataset or "",
        ctx=load_context(dataset or "yelp"),
        trial_key=f"optimise_{scope}",
        sandbox=None,
    )
    allowed = TOOLS if dataset else ["mcp__dab__write_notes"]
    cwd = isolated_cwd()
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=resolve_model(cfg.model),
        tools=[],
        allowed_tools=allowed,
        mcp_servers={"dab": _server(state, sess, guard, dataset)},
        strict_mcp_config=True,
        permission_mode="bypassPermissions",
        max_turns=cfg.max_turns if dataset else SYSTEM_PASS_TURNS,
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


async def optimise(run_id: str, into: str, workers: int = 4) -> dict[str, Any]:
    from dab_bench.eval import golden
    from dab_bench.eval.scorecard import load_optimise_split, load_scorecard, score_run

    target = AGENTS_DIR / into
    if target.exists():
        raise FileExistsError(f"{target} exists; a version is never overwritten")
    split = load_optimise_split()
    if split is None:
        raise FileNotFoundError("no train/held-out split: run `dab split-optimise` first")
    meta, results, traces = _read_run(run_id)
    source = load_version(meta["agent"])
    if not source.submits_sql:
        raise ValueError(f"{source.name} has no submit_answer: nothing for the optimiser to read")
    card = load_scorecard(run_id) or score_run(run_id)
    goldens = golden.current()
    train = set(split["train"])
    optimiser = load_version(OPTIMISER_DIR.name)
    guard = load_guard(NOTES_MAX_CHARS)
    datasets = sorted(
        {
            q["query_id"].split("/")[0]
            for q in card["questions"]
            if q["query_id"] in train
            and q["golden_id"] is not None
            and False in (q["answer"], q["sql"], q["decision"])
        }
    )
    sem = asyncio.Semaphore(max(1, workers))
    started = datetime.now(UTC).isoformat()

    async def one(ds: str) -> Session:
        message, failed = briefing(ds, source, card, results, traces, goldens, train)
        async with sem:
            s = await run_session(ds, optimiser.system_prompt, message, guard, optimiser, ds)
        s.questions = failed
        return s

    sessions = await asyncio.gather(*(one(ds) for ds in datasets))
    notes = dict(source.notes)
    for s in sessions:
        if s.notes is not None:
            notes[s.scope] = s.notes
    system_md = source.system_prompt
    sys_guard = Guard(guard.questions, guard.golds, guard.golden_sqls, SYSTEM_MAX_CHARS)
    system_pass = await run_session(
        "system.md",
        (OPTIMISER_DIR / "system_pass.md").read_text(),
        system_briefing(source, card, {s.scope: s.notes or "" for s in sessions}),
        sys_guard,
        optimiser,
        None,
    )
    if system_pass.notes:
        system_md = system_pass.notes.rstrip() + "\n"

    # the new version: a copy, the notes, the lineage
    shutil.copytree(source.path, target, ignore=shutil.ignore_patterns("optimise.json"))
    cfg = yaml.safe_load((target / "agent.yaml").read_text()) or {}
    header = (source.path / "agent.yaml").read_text().split("\n")
    comments = [ln for ln in header if ln.startswith("#")]
    cfg["challenger_of"] = source.name
    (target / "agent.yaml").write_text(
        "\n".join(
            [f"# {into}: {source.name} after one optimisation round of run {run_id} (s06, B9)"]
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
    all_sessions = [*sessions, system_pass]
    record = {
        "version": into,
        "challenger_of": source.name,
        "source_run": run_id,
        "source_fingerprint": source.fingerprint,
        "fingerprint": new.fingerprint,
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "optimiser": {
            "model": resolve_model(optimiser.config.model),
            "effort": optimiser.config.effort,
        },
        "split": {k: len(v) for k, v in split.items()},
        "source_scorecard": card["totals"],
        "cost_usd": sum(s.cost_usd or 0.0 for s in all_sessions),
        "sessions": [{k: v for k, v in asdict(s).items() if k != "trace"} for s in all_sessions],
        "system_md_changed": system_md != source.system_prompt,
    }
    (target / "optimise.json").write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n")
    tdir = RUNS_DIR / run_id / "optimise" / into
    tdir.mkdir(parents=True, exist_ok=True)
    for s in all_sessions:
        name = s.scope.replace(".", "_")
        (tdir / f"{name}.json").write_text(
            json.dumps(asdict(s), ensure_ascii=False, indent=1, default=str)
        )
    try:
        record["mlflow_run_id"] = _log(record, target, tdir)
        from dab_bench.tracking.prompts import register

        record["prompt_version"] = register(new)
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
    )
    if s.notes:
        (target / "system.md").write_text(s.notes.rstrip() + "\n")
    new = load_version(into)
    entry = {k: v for k, v in asdict(s).items() if k != "trace"}
    record["sessions"] = [x for x in record["sessions"] if x["scope"] != "system.md"] + [entry]
    record["system_md_changed"] = new.system_prompt != source.system_prompt
    record["fingerprint"] = new.fingerprint
    record["cost_usd"] = sum(x.get("cost_usd") or 0.0 for x in record["sessions"])
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
