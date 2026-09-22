"""`dab eval`: run an agent version over a split, judge every answer, write `runs/<id>/`.

The run folder is the record — the tracker logs it, the compare reads two of
them, the explorer lists them. `results.jsonl` is rewritten after every trial
so a killed run keeps its finished trials. Each answer is judged by the same
`validate.py` the leaderboard rows were rescored with (`eval/validators.py`),
in a worker process because the judge is alarm-bounded on its main thread.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Console

from dab_bench.agent.llm import EFFORT, resolve_model, short_model
from dab_bench.agent.prompt import DatasetContext, compose_system_prompt, load_context
from dab_bench.agent.sandbox import Sandbox, SandboxError
from dab_bench.agent.session import Solve, save_trace, solve, trial_key
from dab_bench.agent.versions import AgentVersion, load_version
from dab_bench.config import CONTEXT_DIR, RUNS_DIR, SOURCE_PATH, UPSTREAM_DIR, settings
from dab_bench.eval.score import Summary, TrialResult, read_results, summarise, write_results
from dab_bench.eval.splits import Query, load_split

console = Console()


@dataclass
class RunMeta:
    run_id: str
    agent: str
    fingerprint: str
    context_sha: str
    model: str
    effort: str
    split: str
    n_queries: int
    trials: int
    workers: int
    hints: bool
    dry_run: bool
    started_at: str
    max_turns: int
    finished_at: str | None = None
    code_sha: str = "unknown"
    upstream_commit: str = "unknown"
    summary: dict[str, Any] | None = None
    mlflow_run_id: str | None = None
    note: str = ""
    query_ids: list[str] = field(default_factory=list)
    kind: str = "eval"
    challenger_of: str | None = (
        None  # the champion run this run is measured against (loop scaffolding)
    )
    sandbox: str | None = None


def new_run_id(version: AgentVersion, model: str, split: str, hints: bool) -> str:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = f"{ts}_{version.name}_{split}_{short_model(model)}" + ("_hints" if hints else "")
    run_id, n = base, 1
    while (RUNS_DIR / run_id).exists():
        n += 1
        run_id = f"{base}-{n}"
    return run_id


# ----------------------------------------------------------------------------- judging


def _judge_in_worker(folder: str, query_id: int, answer: str, timeout_s: int) -> dict[str, Any]:
    from dab_bench.eval.validators import judge, load_validator, query_dir

    try:
        fn = load_validator(query_dir(UPSTREAM_DIR, folder, query_id), UPSTREAM_DIR)
    except Exception as e:  # noqa: BLE001 - a missing validator is "not scored", not a crash
        return {"passed": None, "reason": f"validator not loaded: {type(e).__name__}: {e}"[:300]}
    v = judge(fn, answer, timeout_s=timeout_s)
    return {"passed": v.ok, "reason": v.reason[:500], "timed_out": v.timed_out}


class Judge:
    """Validators run in a process pool: `signal.alarm` needs a main thread, and the
    harness's main thread is the event loop."""

    def __init__(self, workers: int = 2, timeout_s: int = 30) -> None:
        self.pool = ProcessPoolExecutor(max_workers=workers)
        self.timeout_s = timeout_s

    async def judge(self, query: Query, answer: str) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self.pool, _judge_in_worker, query.folder, query.query_id, answer, self.timeout_s
        )

    def close(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)


# ----------------------------------------------------------------------------- one trial


def _result_from(query: Query, trial: int, s: Solve, verdict: dict[str, Any]) -> TrialResult:
    return TrialResult(
        query_id=query.id,
        dataset=query.dataset,
        trial=trial,
        question=query.question,
        answer=s.answer,
        passed=verdict.get("passed"),
        reason=str(verdict.get("reason") or ""),
        n_turns=s.n_turns,
        duration_ms=s.duration_ms,
        cost_usd=s.cost_usd,
        input_tokens=s.input_tokens,
        cache_read_tokens=s.cache_read_tokens,
        cache_creation_tokens=s.cache_creation_tokens,
        output_tokens=s.output_tokens,
        tool_calls=len(s.tool_calls),
        error=s.error,
        terminal_reason=s.terminal_reason,
        timed_out=s.timed_out or bool(verdict.get("timed_out")),
        rate_limited=s.rate_limited,
        session_id=s.session_id,
    )


async def run_eval(
    agent: str = "champion",
    split: str = "smoke",
    trials: int = 1,
    workers: int = 4,
    model: str | None = None,
    effort: str | None = None,
    hints: bool | None = None,
    dry_run: bool = False,
    query_ids: list[str] | None = None,
    note: str = "",
    track: bool = True,
    challenger_of: str | None = None,
    judge_timeout_s: int = 30,
    resume: str | None = None,
) -> tuple[RunMeta, list[TrialResult]]:
    """`resume`: re-run only the trials of an existing run folder that were rate-limited or
    errored, into the same folder, keeping every finished trial and its trace."""
    if resume:
        prior_meta, prior = load_run(resume)
        agent, split, trials = prior_meta.agent, prior_meta.split, prior_meta.trials
        model, effort, hints = prior_meta.model, prior_meta.effort, prior_meta.hints
        challenger_of = prior_meta.challenger_of
        note = note or prior_meta.note
    version = load_version(agent)
    cfg = version.config
    model_id = resolve_model(model or cfg.model)
    eff = effort or cfg.effort or EFFORT
    use_hints = cfg.hints if hints is None else hints
    queries = load_split(split)
    if query_ids:
        wanted = set(query_ids)
        queries = [q for q in queries if q.id in wanted]
    datasets = sorted({q.dataset for q in queries})
    contexts: dict[str, DatasetContext] = {d: load_context(d) for d in datasets}
    context_sha = _combined_sha(contexts)
    run_id = resume or new_run_id(version, model_id, split, use_hints)
    run_dir = RUNS_DIR / run_id
    (run_dir / "traces").mkdir(parents=True, exist_ok=True)
    keep: dict[tuple[str, int], TrialResult] = {}
    if resume:
        keep = {
            (r.query_id, r.trial): r
            for r in prior
            if not r.rate_limited and not (r.error and r.passed is None)
        }
    upstream_commit = "unknown"
    if SOURCE_PATH.exists():
        upstream_commit = str(json.loads(SOURCE_PATH.read_text()).get("commit", "unknown"))
    meta = RunMeta(
        run_id=run_id,
        agent=version.name,
        fingerprint=version.fingerprint,
        context_sha=context_sha,
        model=model_id,
        effort=eff,
        split=split,
        n_queries=len(queries),
        trials=trials,
        workers=workers,
        hints=use_hints,
        dry_run=dry_run,
        started_at=prior_meta.started_at if resume else datetime.now(UTC).isoformat(),
        max_turns=cfg.max_turns,
        code_sha=settings().code_sha,
        upstream_commit=upstream_commit,
        note=note,
        query_ids=[q.id for q in queries],
        challenger_of=challenger_of,
    )
    _write_meta(run_dir, meta)
    _copy_agent_files(run_dir, version, contexts, use_hints)

    if track and not dry_run:
        from dab_bench.tracking.mlflow_log import preflight

        preflight()  # fail fast: the platform's rule, never a silent local store

    sandbox: Sandbox | None = None
    if not dry_run:
        try:
            sandbox = Sandbox.start(run_id)
            meta.sandbox = sandbox.name
        except SandboxError as e:
            console.print(f"[yellow]sandbox: {e} — execute_python will be unavailable[/]")
    judge = Judge(workers=2, timeout_s=judge_timeout_s)
    console.rule(
        f"[bold]{run_id}[/] · {len(queries)} queries × {trials} · {model_id} @ {eff} · "
        f"workers={workers} · hints={use_hints}" + (" · DRY RUN" if dry_run else "")
    )
    sem = asyncio.Semaphore(max(1, workers))
    results: dict[tuple[str, int], TrialResult] = dict(keep)
    order = [(q, t) for q in queries for t in range(1, trials + 1)]
    todo = [(q, t) for q, t in order if (q.id, t) not in keep]
    if resume:
        console.print(f"resuming {run_id}: {len(keep)} trials kept, {len(todo)} to run")
    started_run = time.time()

    async def one(query: Query, trial: int) -> None:
        async with sem:
            t0 = time.time()
            if dry_run:
                s = Solve(
                    query.id, query.dataset, trial, "dry-run", "dry-run", model=model_id, effort=eff
                )
                s.context_sha = contexts[query.dataset].context_sha
                s.trace = [
                    {
                        "role": "system",
                        "content": compose_system_prompt(
                            version.system_prompt, contexts[query.dataset], use_hints
                        ),
                    },
                    {"role": "user", "content": query.question},
                ]
            else:
                s = await solve(
                    version,
                    query,
                    contexts[query.dataset],
                    trial,
                    sandbox,
                    model=model_id,
                    effort=eff,
                    hints=use_hints,
                )
            verdict = (
                await judge.judge(query, s.answer)
                if s.answer
                else {"passed": False, "reason": "empty answer"}
            )
            r = _result_from(query, trial, s, verdict)
            trace_path = run_dir / "traces" / f"{trial_key(query, trial)}.json"
            save_trace(trace_path, s)
            r.trace_file = str(trace_path.relative_to(run_dir))
            if track and not dry_run:
                try:
                    from dab_bench.tracking.tracing import log_trial_trace

                    r.mlflow_trace_id = log_trial_trace(meta, r, s, t0)
                except Exception as e:  # noqa: BLE001 - a trace never fails a trial
                    console.print(f"[yellow]trace not logged: {type(e).__name__}: {e}[/]")
            results[(query.id, trial)] = r
            if r.rate_limited:
                r.passed = None
                r.reason = "rate limited (not scored); re-run with --resume"
            mark = {True: "[green]pass[/]", False: "[red]FAIL[/]", None: "[dim]—[/]"}[r.passed]
            console.print(
                f"  {query.id:<20} t{trial} {mark}  {r.answer[:70]!r}"
                f"  ({time.time() - t0:.0f}s, {r.n_turns} turns, {r.tool_calls} tools"
                + (f", ${r.cost_usd:.3f}" if r.cost_usd else "")
                + ")"
                + (f"  [red]{r.error}[/]" if r.error else "")
            )
            write_results(
                run_dir / "results.jsonl",
                [results[(q.id, t)] for q, t in order if (q.id, t) in results],
            )

    try:
        await asyncio.gather(*(one(q, t) for q, t in todo))
    finally:
        judge.close()
        if sandbox is not None:
            sandbox.stop()
    ordered = [results[(q.id, t)] for q, t in order if (q.id, t) in results]
    write_results(run_dir / "results.jsonl", ordered)
    summary = summarise(ordered)
    meta.finished_at = datetime.now(UTC).isoformat()
    meta.summary = asdict(summary)
    _write_meta(run_dir, meta)
    _print_summary(summary, time.time() - started_run)
    if track and not dry_run:
        try:
            from dab_bench.tracking.mlflow_log import log_run
            from dab_bench.tracking.tracing import flush

            flush()
            meta.mlflow_run_id = log_run(run_dir, meta, ordered)
            _write_meta(run_dir, meta)
            console.print(f"mlflow run {meta.mlflow_run_id}")
        except Exception as e:  # noqa: BLE001 - tracking down never fails an eval
            console.print(
                f"[yellow]mlflow: not logged ({type(e).__name__}: {e}) — `dab runs log {run_id}` re-logs it[/]"
            )
    return meta, ordered


def _combined_sha(contexts: dict[str, DatasetContext]) -> str:
    import hashlib

    h = hashlib.sha256()
    for d in sorted(contexts):
        h.update(d.encode())
        h.update(contexts[d].context_sha.encode())
    return h.hexdigest()[:12]


def _copy_agent_files(
    run_dir: Path, version: AgentVersion, contexts: dict[str, DatasetContext], hints: bool
) -> None:
    (run_dir / "agent").mkdir(exist_ok=True)
    for name, text in version.files().items():
        (run_dir / "agent" / name).write_text(text)
    for d, ctx in contexts.items():
        (run_dir / "agent" / f"system.{d}.md").write_text(
            compose_system_prompt(version.system_prompt, ctx, hints=hints)
        )
        dst = run_dir / "context" / d
        dst.mkdir(parents=True, exist_ok=True)
        for f in ("summary.md", "pitfalls.md", "curation.json"):
            src = CONTEXT_DIR / d / f
            if src.exists():
                shutil.copy(src, dst / f)


def _print_summary(s: Summary, seconds: float) -> None:
    if s.scored == 0:
        console.print(f"[bold]{s.n} trials[/], none scored")
        return
    ds = " · ".join(f"{k} {v['passed']}/{v['n']}" for k, v in sorted(s.per_dataset.items()))
    console.print(
        f"[bold]{s.passed}/{s.scored} pass[/] (micro {s.pass_rate_micro:.0%}, macro {s.pass_rate_macro:.0%})  "
        f"errors={s.errors} timeouts={s.timeouts} rate_limited={s.rate_limited}  ${s.cost_usd:.2f}  {seconds / 60:.0f} min\n  {ds}"
    )


def _write_meta(run_dir: Path, meta: RunMeta) -> None:
    (run_dir / "run.json").write_text(json.dumps(asdict(meta), indent=2) + "\n")


def load_run(run_id: str) -> tuple[RunMeta, list[TrialResult]]:
    run_dir = RUNS_DIR / run_id
    meta = RunMeta(**json.loads((run_dir / "run.json").read_text()))
    results = (
        read_results(run_dir / "results.jsonl") if (run_dir / "results.jsonl").exists() else []
    )
    return meta, results


def list_runs() -> list[RunMeta]:
    if not RUNS_DIR.exists():
        return []
    out = []
    for d in sorted(RUNS_DIR.iterdir()):
        if (d / "run.json").exists():
            out.append(RunMeta(**json.loads((d / "run.json").read_text())))
    return out
