"""`dab` — the command line behind every Makefile target."""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()

data_app = typer.Typer(
    no_args_is_help=True, help="The 12 datasets' stores: download, load into Postgres, check."
)
app.add_typer(data_app, name="data")


def _datasets_arg(datasets: str | None) -> list[str] | None:
    return [d.strip() for d in datasets.split(",") if d.strip()] if datasets else None


@data_app.command("download")
def data_download(datasets: str | None = None, dry_run: bool = False) -> None:
    """Fetch the in-scope database files from Hugging Face into data/upstream (sha256-verified)."""
    from dab_bench.data.download import download

    r = download(_datasets_arg(datasets), dry_run=dry_run)
    console.print(
        f"verified {len(r.verified)} · fetched {len(r.fetched)} · not in manifest {len(r.skipped)}"
        + (f" · [red]failed {r.failed}[/]" if r.failed else "")
    )
    for f in r.fetched:
        console.print(f"  {'would fetch' if dry_run else 'fetched'} {f}")


@data_app.command("init")
def data_init() -> None:
    """Apply infra/roles.sql (schema + roles) as the Postgres superuser. Idempotent."""
    from dab_bench.data import pg

    if not pg.reachable(None) and not pg.reachable(
        __import__("dab_bench.config").config.settings().pg_superuser_url
    ):
        console.print("[red]central Postgres is not reachable[/] — run `make platform-up` first")
        raise typer.Exit(1)
    pg.init_schema()
    console.print("schema dataagentbench · roles dab_owner, dab_agent ready")


@data_app.command("load")
def data_load(datasets: str | None = None) -> None:
    """Load every store into dataagentbench.<dataset>_<table> (drops and recreates)."""
    import time

    from dab_bench.data.load import LoadedTable, load
    from dab_bench.data.stores import Store

    t0 = time.time()

    def progress(s: Store, tables: list[LoadedTable]) -> None:
        names = ", ".join(f"{t.table} ({t.source_rows:,})" for t in tables)
        console.print(
            f"  [green]{s.dataset}/{s.name}[/] ({s.engine}) → {names}  [{time.time() - t0:.0f}s]"
        )

    r = load(_datasets_arg(datasets), on_progress=progress)
    console.print(f"loaded {len(r.tables)} tables in {time.time() - t0:.0f}s")
    for e in r.errors:
        console.print(f"[red]error[/] {e}")
    if r.errors:
        raise typer.Exit(1)


@data_app.command("smoke")
def data_smoke() -> None:
    """Zero-model proof the central database serves this project: the agent role can read the
    benchmark schema and nothing else, the owner can write; exit 1 on any miss."""
    from dab_bench.config import PG_SCHEMA
    from dab_bench.data import pg

    with pg.connect_agent() as agent:
        n = agent.execute(
            "select count(*) from pg_tables where schemaname = %s", (PG_SCHEMA,)
        ).fetchone()
        tables = int(n[0]) if n else 0
        first = agent.execute(
            "select tablename from pg_tables where schemaname = %s order by 1 limit 1", (PG_SCHEMA,)
        ).fetchone()
        if not first:
            console.print(f"[red]schema {PG_SCHEMA} has no tables[/] — run `make data`")
            raise typer.Exit(1)
        agent.execute(f'select 1 from {PG_SCHEMA}."{first[0]}" limit 1').fetchall()
        try:
            agent.execute(f"create table {PG_SCHEMA}.__smoke_should_fail (x int)")
        except Exception:  # noqa: BLE001 - the refusal is the pass condition
            pass
        else:
            console.print("[red]dab_agent could CREATE TABLE[/] — roles.sql not applied?")
            raise typer.Exit(1)
    with pg.connect() as owner:
        owner.execute(
            f"create table if not exists {PG_SCHEMA}.__smoke (at timestamptz default now())"
        )
        owner.execute(f"insert into {PG_SCHEMA}.__smoke default values")
        owner.execute(f"drop table {PG_SCHEMA}.__smoke")
    console.print(
        f"central database ok · {tables} tables in {PG_SCHEMA} · agent read-only · owner writes"
    )


@data_app.command("check")
def data_check(datasets: str | None = None) -> None:
    """Live row count per loaded table against the source count; exit 1 on any mismatch."""
    from dab_bench.data.load import check

    rows = check(_datasets_arg(datasets))
    t = Table(box=None)
    for c in ("dataset", "table", "source", "live", "ok"):
        t.add_column(c)
    bad = 0
    ds_ok: dict[str, bool] = {}
    for r in rows:
        t.add_row(
            r.dataset, r.table, str(r.source_rows), str(r.live_rows), "✓" if r.ok else "[red]✗[/]"
        )
        ds_ok[r.dataset] = ds_ok.get(r.dataset, True) and r.ok
        bad += 0 if r.ok else 1
    console.print(t)
    console.print(
        f"datasets ok: {sum(ds_ok.values())}/{len(ds_ok)} · tables ok: {len(rows) - bad}/{len(rows)}"
    )
    if bad:
        raise typer.Exit(1)


@app.command()
def upstream(commit: str | None = None, force: bool = False) -> None:
    """Shallow-clone the benchmark into data/upstream (LFS skipped; no database bytes)."""
    from dab_bench.data.upstream import clone

    up = clone(commit=commit, force=force)
    console.print(f"upstream at {up.path} · commit {up.commit}")


@app.command()
def ingest() -> None:
    """Walk data/upstream and write data/index/ and data/answers/."""
    from dab_bench.data.ingest import run

    r = run()
    console.print(
        f"ingested commit {r.commit}: {r.datasets_in_scope} datasets / {r.queries_in_scope} queries in scope "
        f"(upstream has {r.datasets_total} / {r.queries_total}; deferred {len(r.deferred_datasets)} datasets, "
        f"{r.deferred_queries} queries) · {r.answer_rows} answer rows copied, {r.answer_rows_unmatched} unmatched"
    )
    for w in r.warnings:
        console.print(f"[yellow]warning[/yellow] {w}")


@app.command()
def rescore(workers: int = 4, timeout: int = 30, limit: int | None = None) -> None:
    """Judge every committed answer with its query's validate.py; write data/index/trials.json."""
    from dab_bench.eval.rescore import run

    s = run(workers=workers, timeout_s=timeout, limit=limit)
    console.print(
        f"rescored {s['rows']} answers over {s['queries']} queries in {s['seconds']:.0f}s · "
        f"{s['timed_out']} timed out · never passed: {', '.join(s['never_passed']) or 'none'}"
    )


@app.command()
def stats(as_json: bool = False) -> None:
    """The numbers the README quotes, from the index."""
    from dab_bench.data.index import stats as _stats

    s = _stats()
    if as_json:
        console.print_json(json.dumps(s))
        return
    t = Table(show_header=False, box=None)
    for k, v in s.items():
        t.add_row(k, json.dumps(v) if isinstance(v, dict | list) else str(v))
    console.print(t)


context_app = typer.Typer(
    no_args_is_help=True, help="The context pack: build (code) and curate (agent)."
)
app.add_typer(context_app, name="context")


@context_app.command("build")
def context_build(datasets: str | None = None) -> None:
    """Generate schema.md, profile.json, samples/, joins.md, description/hints per dataset from Postgres."""
    import time

    from dab_bench.context.build import build

    t0 = time.time()
    for r in build(_datasets_arg(datasets)):
        console.print(
            f"  [green]{r.dataset}[/] · {r.tables} tables · {r.joins} join pairs → {r.path}  [{time.time() - t0:.0f}s]"
        )


@context_app.command("curate")
def context_curate(datasets: str | None = None, model: str | None = None) -> None:
    """Run the curator agent once per dataset → summary.md + pitfalls.md (Sonnet 5, no questions seen)."""
    import json

    from dab_bench.config import CONTEXT_DIR, DATASETS_PATH
    from dab_bench.context.curate import curate
    from dab_bench.tracking.mlflow_log import TrackingDownError, preflight

    keys = _datasets_arg(datasets) or [
        d["key"] for d in json.loads(DATASETS_PATH.read_text()) if d.get("released", True)
    ]
    missing = [k for k in keys if not (CONTEXT_DIR / k / "tables.json").exists()]
    if missing:
        console.print(f"[red]no generated pack for {missing}[/] — run `dab context build` first")
        raise typer.Exit(1)
    try:
        preflight()
    except TrackingDownError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(1) from None
    total = 0.0
    for c in curate(keys, model=model):
        total += c.cost_usd or 0.0
        if c.error:
            console.print(f"  [red]{c.dataset}[/] error: {c.error}")
        else:
            console.print(
                f"  [green]{c.dataset}[/] · summary {len(c.summary.splitlines())} lines · "
                f"pitfalls {len(c.pitfalls.splitlines())} lines · {c.input_tokens:,} in / {c.output_tokens:,} out · "
                f"${c.cost_usd or 0:.3f} · {c.duration_ms / 1000:.0f}s"
            )
    console.print(f"curated {len(keys)} datasets · ${total:.2f}")


@app.command("eval")
def eval_cmd(
    agent: str = "champion",
    split: str = "smoke",
    trials: int = 1,
    workers: int = 4,
    model: str | None = None,
    effort: str | None = None,
    hints: bool | None = None,
    dry_run: bool = False,
    queries: str | None = None,
    note: str = "",
    no_mlflow: bool = False,
    challenger_of: str | None = None,
    resume: str | None = None,
) -> None:
    """Run an agent version over a split; judge every answer; write runs/<id>/ and log to MLflow.

    --resume RUN_ID re-runs only that run's rate-limited or errored trials into the same folder."""
    import asyncio

    from dab_bench.eval.runner import run_eval
    from dab_bench.tracking.mlflow_log import TrackingDownError

    try:
        meta, _ = asyncio.run(
            run_eval(
                agent=agent,
                split=split,
                trials=trials,
                workers=workers,
                model=model,
                effort=effort,
                hints=hints,
                dry_run=dry_run,
                query_ids=_datasets_arg(queries),
                note=note,
                track=not no_mlflow,
                challenger_of=challenger_of,
                resume=resume,
            )
        )
    except TrackingDownError as e:
        console.print(f"[red]{e}[/]  (or pass --no-mlflow for an offline test run)")
        raise typer.Exit(1) from None
    console.print(f"run folder: runs/{meta.run_id}")


runs_app = typer.Typer(no_args_is_help=True, help="Run folders: list, profile, re-log.")
app.add_typer(runs_app, name="runs")


@runs_app.command("list")
def runs_list() -> None:
    """Every run folder with its headline numbers."""
    from dab_bench.eval.runner import list_runs

    t = Table(box=None)
    for c in ("run", "agent", "split", "model", "trials", "pass", "macro", "cost", "note"):
        t.add_column(c)
    for m in list_runs():
        s = m.summary or {}
        macro = s.get("pass_rate_macro")
        t.add_row(
            m.run_id,
            f"{m.agent}@{m.fingerprint}",
            m.split,
            m.model.replace("claude-", ""),
            str(m.trials),
            f"{s.get('passed', '—')}/{s.get('scored', '—')}",
            f"{macro:.0%}" if isinstance(macro, float) else "—",
            f"${s.get('cost_usd', 0):.2f}" if s else "—",
            m.note[:40],
        )
    console.print(t)


@runs_app.command("profile")
def runs_profile(run_id: str) -> None:
    """Token and turn profile of a run: mean / p50 / p95 / max per trial, the same numbers the explorer shows."""
    from dab_bench.eval.runner import load_run
    from dab_bench.eval.score import PROFILE_METRICS, profile

    meta, results = load_run(run_id)
    if not results:
        console.print("no results")
        raise typer.Exit(1)
    p = profile(results)
    t = Table(box=None)
    for c in ("metric", "mean", "p50", "p95", "max", "total"):
        t.add_column(c)
    for key, label in PROFILE_METRICS:
        m = p["metrics"][key]
        f = "{:,.3f}" if key == "cost_usd" else "{:,.0f}"
        t.add_row(label, *(f.format(m[k]) for k in ("mean", "p50", "p95", "max", "sum")))
    console.print(t)
    hit = p["cache_hit_rate"]
    console.print(
        f"{p['n']} trials ran · cache hit {hit:.0%} · cost per pass "
        f"{p['cost_per_pass'] if p['cost_per_pass'] is None else f'${p["cost_per_pass"]:.2f}'} · "
        f"{meta.model} @ {meta.effort} · fingerprint {meta.fingerprint} · context {meta.context_sha}"
    )


@runs_app.command("backfill-usage")
def runs_backfill_usage(run_id: str) -> None:
    """Add per-message token usage to a run's trace files from the Agent SDK's own session
    transcripts (~/.claude/projects/<cwd>/<session_id>.jsonl), for runs made before the
    harness recorded it. Skips a trace whose transcript is missing or does not line up."""
    from dab_bench.agent.session import backfill_usage
    from dab_bench.config import RUNS_DIR

    done, skipped = backfill_usage(RUNS_DIR / run_id)
    console.print(f"{done} traces updated, {skipped} skipped")


@runs_app.command("log")
def runs_log(run_id: str) -> None:
    """Re-log a run folder to the central MLflow (after an outage, or for a run made with --no-mlflow)."""
    from dab_bench.eval.runner import _write_meta, load_run
    from dab_bench.tracking.mlflow_log import log_run, preflight

    preflight()
    meta, results = load_run(run_id)
    from dab_bench.config import RUNS_DIR

    meta.mlflow_run_id = log_run(RUNS_DIR / run_id, meta, results)
    _write_meta(RUNS_DIR / run_id, meta)
    console.print(f"logged {run_id} → mlflow run {meta.mlflow_run_id}")


@app.command()
def serve(port: int = 8091, host: str = "127.0.0.1", reload: bool = False) -> None:
    """Run the API (and the built explorer when frontend/dist exists)."""
    import uvicorn

    uvicorn.run(
        "dab_bench.serving.app:create_app", host=host, port=port, factory=True, reload=reload
    )


if __name__ == "__main__":
    app()
