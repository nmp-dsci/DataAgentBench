"""`dab` — the command line behind every Makefile target."""

from __future__ import annotations

import json
from pathlib import Path

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


@data_app.command("load-questions")
def data_load_questions() -> None:
    """Copy data/index/queries.json into dataagentbench_meta.queries for ad-hoc SQL.

    The JSON stays the record; this table is dropped and rebuilt. It holds gold
    answers, so it lives outside the schema the agent can read.
    """
    from dab_bench.data.meta import load_questions

    r = load_questions()
    console.print(
        f"{r.rows} questions → {r.schema}.{r.table} (upstream {r.upstream_commit[:7]}); "
        "not readable by dab_agent"
    )


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
def diagnose(
    run_id: str,
    refresh: bool = False,
    show: int = 60,
    ledger: bool = typer.Option(
        False, help="also run the reader (Sonnet 5): the SQL ledger, where each statement breaks"
    ),
    model: str | None = typer.Option(
        None, help="the reader's model for this ledger (haiku | sonnet | opus); default agent.yaml"
    ),
) -> None:
    """The scorecard of a run: answer / SQL / decision per question, a category per failure,
    and what to optimise first. Computed after the run (goldens re-run as dab_agent) and kept
    in runs/<id>/scorecard.json; --refresh recomputes it. --ledger (plan s08) has the reader
    write seven lines per golden (cached) and per failed statement into runs/<id>/ledger.json,
    and a failed trial's category becomes the step it breaks at; with --refresh the ledger's
    comparisons are re-read too."""
    from dab_bench.eval.scorecard import load_scorecard, score_run

    card = None if refresh or ledger else load_scorecard(run_id)
    if ledger:
        import asyncio

        from dab_bench.eval.ledger import build

        score_run(run_id)  # the comparisons read the fresh SQL verdicts
        led = asyncio.run(build(run_id, refresh=refresh, model=model))
        console.print(
            f"ledger: {len(led['goldens'])} goldens, {len(led['questions'])} comparisons, "
            f"${led['cost_usd']:.2f}"
            + (f", [red]{len(led['errors'])} error(s)[/]" if led["errors"] else "")
        )
        for e in led["errors"]:
            console.print(f"  [red]{e}[/]")
    if card is None:
        card = score_run(run_id)
        from dab_bench.config import RUNS_DIR
        from dab_bench.eval.runner import load_run

        meta, _ = load_run(run_id)
        if meta.mlflow_run_id:
            try:
                from dab_bench.tracking.mlflow_log import log_scorecard

                log_scorecard(meta.mlflow_run_id, RUNS_DIR / run_id)
            except Exception as e:  # noqa: BLE001 - the folder is the record
                console.print(f"[yellow]mlflow: scorecard not re-logged ({e})[/]")
    tot = card["totals"]
    head = "   ".join(f"{k} {v['passed']}/{v['n']}" for k, v in tot.items())
    console.print(f"[bold]{run_id}[/]   {head}")
    for split, st in (card.get("by_split") or {}).items():
        console.print(
            f"  {split:<8} " + "   ".join(f"{k} {v['passed']}/{v['n']}" for k, v in st.items())
        )
    if card["optimise_first"]:
        console.print("optimise first:")
        for o in card["optimise_first"]:
            qs = ", ".join(o["queries"][:4]) + (", …" if len(o["queries"]) > 4 else "")
            console.print(f"  {o['category']:<26} {o['n']:>3}   {qs}")
    t = Table(box=None)
    for c in ("question", "split", "answer", "SQL", "decision", "category", "detail"):
        t.add_column(c)

    def mark(v: bool | None) -> str:
        return "—" if v is None else "[green]pass[/]" if v else "[red]fail[/]"

    for q in card["questions"][:show]:
        t.add_row(
            q["query_id"],
            q.get("split") or "",
            mark(q["answer"]),
            mark(q["sql"]),
            mark(q["decision"]),
            q["category"] if q["category"] != "solved" else "—",
            q["detail"][:70],
        )
    console.print(t)


@app.command()
def optimise(
    run_id: str | None = typer.Argument(
        None, help="the run to learn from; default the champion's newest full run (s13)"
    ),
    into: str = typer.Option(..., help="the new version's name, e.g. v2_sql"),
    workers: int = 4,
    system_pass_only: bool = typer.Option(
        False, help="re-run only the cross-dataset system.md pass for an existing INTO"
    ),
    components: bool = typer.Option(
        True,
        help="s08 (D32 B): component sessions write the SQL playbook in system.md; "
        "--no-components runs round 1's per-dataset sessions and system pass",
    ),
    model: str | None = typer.Option(
        None,
        help="the optimiser's model for this round (haiku | sonnet | opus); default agent.yaml",
    ),
    train: str = typer.Option(
        "split",
        help="split: read the training questions' errors only; all: every error of the 54, "
        "wrong answers without a golden included (s11, D38)",
    ),
    strict: bool = typer.Option(
        False, help="s11 (D40 B): guards G1 review, G2 audit, G3 breadth, G4 no routing"
    ),
    history: bool = typer.Option(
        True,
        help="s13 (D42 A): every session reads each failed question's history and the rounds "
        "from the champion that lost, built from MLflow",
    ),
) -> None:
    """One optimisation round: the optimiser (Sonnet 5, medium) reads RUN's failed train
    questions and writes agents/INTO/ = the run's version + a playbook section per step at
    which statements break (across datasets, from the ledger: run `dab diagnose RUN --ledger`
    first) + dataset notes. Every edit is checked for question text, gold values and golden
    SQL; the held-out questions are never shown. From s13 the run must be the champion's."""
    import asyncio

    from dab_bench.agent.optimise import NotChampionError
    from dab_bench.agent.optimise import optimise as _optimise
    from dab_bench.tracking.mlflow_log import TrackingDownError, preflight

    try:
        preflight()
    except TrackingDownError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(1) from None
    if system_pass_only:
        from dab_bench.agent.optimise import rerun_system_pass

        rec = asyncio.run(rerun_system_pass(into))
    else:
        if train not in ("split", "all"):
            console.print("[red]--train is split or all[/]")
            raise typer.Exit(1)
        if run_id is None:
            from dab_bench.eval.promote import champion_run

            run_id = champion_run()
            if run_id is None:
                console.print("[red]the champion has no complete full-split run[/]")
                raise typer.Exit(1)
            console.print(f"the champion's run: {run_id}")
        try:
            rec = asyncio.run(
                _optimise(
                    run_id,
                    into,
                    workers=workers,
                    components=components,
                    model=model,
                    train_all=train == "all",
                    strict=strict,
                    history=history,
                )
            )
        except NotChampionError as e:
            console.print(f"[red]{e}[/]")
            raise typer.Exit(1) from None
    for s in rec["sessions"]:
        state = (
            "[red]error[/] " + s["error"]
            if s["error"]
            else "accepted"
            if s["notes"] is not None
            else "[yellow]dropped[/]"
        )
        console.print(
            f"  {s['scope']:<18} {state}  {len(s['notes'] or ''):>5} chars"
            + (f"/{s['budget']}" if s.get("budget") else "")
            + "  "
            f"{len(s['refusals'])} refusal(s)  {s['n_turns']} turns  ${s['cost_usd'] or 0:.3f}"
        )
    console.print(
        f"agents/{into} · fingerprint {rec['fingerprint']} · system.md "
        f"{'changed' if rec['system_md_changed'] else 'unchanged'} · ${rec['cost_usd']:.2f}"
    )
    if (rec.get("guards") or {}).get("g1_review"):
        reviews = [r for s in rec["sessions"] for r in s.get("reviews") or []]
        console.print(
            f"G1 {len(reviews)} review(s), {sum(1 for r in reviews if r.get('decisive'))} "
            f"decisive, {sum(1 for r in reviews if not r.get('reviewed'))} unreviewed · "
            f"${rec.get('reviews_cost_usd') or 0:.2f} · G2 units reverted: "
            f"{len((rec.get('audit_g2') or {}).get('units_with_gold') or {})} · G3 skipped: "
            f"{', '.join(rec.get('playbook_skipped_g3') or {}) or 'none'}"
        )


@app.command()
def promote(candidates: str | None = None, dry_run: bool = False) -> None:
    """Crown the version that answers best (D46): a challenger passes the leak gate (its round
    ran guards G1–G4, no gold value in its prompt); the highest Pass@1 wins; answers passed of
    the 54 break a tie, then SQL passed of the questions with a golden; then the incumbent;
    then the older run. Each candidate is its newest complete full-split run. Moves
    agents/champion, sets the MLflow prompt alias `champion` and appends the verdict to
    agents/promotions.jsonl."""
    from dab_bench.eval.promote import promote as _promote

    rec = _promote(_datasets_arg(candidates), dry_run=dry_run)
    t = Table(box=None)
    for c in ("version", "run", "answer", "SQL", "decision", "Pass@1", "held-out answer", "note"):
        t.add_column(c)
    for c in rec["candidates"]:
        sc = c.get("scorecard") or {}
        ho = (c.get("heldout") or {}).get("answer")
        t.add_row(
            c["version"] + (" ★" if c["version"] == rec["winner"] else ""),
            c["run_id"] or "—",
            f"{c['passed']}/{c['scored']}" if c["passed"] is not None else "—",
            f"{sc['sql']['passed']}/{sc['sql']['n']}" if sc.get("sql", {}).get("n") else "—",
            f"{sc['decision']['passed']}/{sc['decision']['n']}"
            if sc.get("decision", {}).get("n")
            else "—",
            f"{c['pass_at_1']:.3f}" if c.get("pass_at_1") is not None else "—",
            f"{ho['passed']}/{ho['n']}" if ho else "—",
            c["why_not"]
            or (
                ("gate: " + c["gate"]) if c.get("gate") and c["version"] != rec["incumbent"] else ""
            ),
        )
    console.print(t)
    console.print(("[dim]dry run[/] " if dry_run else "") + rec["reason"])


@app.command("history")
def history_cmd(
    champion: str | None = typer.Option(None, help="default: agents/champion"),
    source: str = typer.Option("mlflow", help="mlflow (D42 A) | folders"),
    parity: bool = typer.Option(False, help="also build from the folders and compare"),
) -> None:
    """Every question's record across the versions (s13): the champion's lineage and the rounds
    from it that lost, each question's answer and SQL per version, what changed, and the last
    pass of a regressed question. Built from MLflow; written to runs/<champion run>/history.json,
    which `dab optimise` rebuilds and reads itself."""
    from dab_bench.agent.versions import champion_name
    from dab_bench.eval import history as hist
    from dab_bench.tracking.mlflow_log import TrackingDownError, preflight

    name = champion or champion_name()
    if source == "mlflow":
        try:
            preflight()
        except TrackingDownError as e:
            console.print(f"[red]{e}[/]")
            raise typer.Exit(1) from None
    src: hist.Source = hist.MlflowSource() if source == "mlflow" else hist.FolderSource()
    h = hist.build(src, name)
    path = hist.write(h)
    status: dict[str, int] = {}
    for x in h["questions"].values():
        status[x["status"]] = status.get(x["status"], 0) + 1
    console.print(
        f"{name} · run {h['champion_run']} · versions "
        + " → ".join(
            v["version"] + {"champion": " ★", "attempt": " ✗"}.get(v["role"], "")
            for v in h["versions"]
        )
    )
    console.print(
        "questions: "
        + " · ".join(f"{k} {v}" for k, v in sorted(status.items()))
        + f" · attempts {', '.join(a['version'] for a in h['attempts']) or 'none'} · {path}"
    )
    if parity:
        other = hist.build(hist.FolderSource() if source == "mlflow" else hist.MlflowSource(), name)
        diffs = hist.parity(h, other)
        console.print(
            "parity: "
            + ("[green]MLflow = folders[/]" if not diffs else "[red]" + "; ".join(diffs) + "[/]")
        )
        if diffs:
            raise typer.Exit(1)


@app.command("mlflow-backfill")
def mlflow_backfill(
    force: bool = typer.Option(False, help="re-log session traces already logged"),
) -> None:
    """Put the records of rounds already run on MLflow (s13, B2 + B3; no model call): each
    round's outcome (from promotions.jsonl and the scorecards) and each optimiser session as a
    trace (from runs/<run>/optimise/<version>/), and each lineage run's current scorecard."""
    from dab_bench.config import RUNS_DIR
    from dab_bench.eval import outcome
    from dab_bench.eval.runner import list_runs
    from dab_bench.tracking.mlflow_log import TrackingDownError, log_scorecard, preflight
    from dab_bench.tracking.tracing import log_round_sessions

    try:
        preflight()
    except TrackingDownError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(1) from None
    for m in list_runs():
        if (
            m.split == "all"
            and not m.dry_run
            and m.mlflow_run_id
            and (RUNS_DIR / m.run_id / "scorecard.json").exists()
        ):
            log_scorecard(m.mlflow_run_id, RUNS_DIR / m.run_id)
    for rec, out in outcome.all_outcomes():
        outcome.relog_record(rec)
        logged = outcome.log_outcome(rec, out)
        tdir = RUNS_DIR / rec["source_run"] / "optimise" / rec["version"]
        n = (
            log_round_sessions(rec, tdir, force=force)
            if rec.get("mlflow_run_id") and tdir.is_dir()
            else 0
        )
        console.print(
            f"  {rec['version']:<8} outcome {out['outcome']:<8}"
            + ("" if logged else " [yellow](no MLflow run)[/]")
            + f" · session traces logged {n}"
        )


@app.command("crossfit")
def crossfit_cmd(
    run_id: str,
    prefix: str = typer.Option(..., help="the version the folds measure, e.g. v7_sql"),
    folds: int = 3,
    model: str | None = typer.Option(None, help="the optimiser's model; default agent.yaml"),
    strict: bool = typer.Option(True, help="guards G1–G4, as the version's own round"),
    workers: int = 4,
) -> None:
    """An out-of-sample score for a round that reads every error (s11): RUN's 54 in FOLDS
    folds by dataset; each fold's round excludes that fold's questions and its prompt
    (<prefix>_f<i>, never listed or promoted) answers only them. Writes
    runs/<RUN>/crossfit/<prefix>.json."""
    import asyncio

    from dab_bench.eval.crossfit import crossfit

    out = asyncio.run(crossfit(run_id, prefix, folds, model=model, strict=strict, workers=workers))
    o = out["out_of_sample"]
    p1 = o["pass_at_1"]
    console.print(
        f"out of sample: answers {o['answer']['passed']}/{o['answer']['n']} · SQL "
        f"{o['sql']['passed']}/{o['sql']['n']} · Pass@1 "
        + (f"{p1:.3f}" if p1 is not None else "—")
        + f" · ${out['cost_usd']:.2f} · runs/{run_id}/crossfit/{prefix}.json"
    )


@app.command("export-submission")
def export_submission_cmd(run_id: str) -> None:
    """RUN's answers in the leaderboard's submission format, to runs/<RUN>/submission.json
    (local only; submitting is a pull request upstream, a separate decision)."""
    from dab_bench.eval.crossfit import export_submission

    path, n = export_submission(run_id)
    console.print(f"{n} answers → {path}")


@app.command("version-model")
def version_model(
    src: str,
    into: str = typer.Option(..., help="the new version's name, e.g. v4_sql"),
    model: str = typer.Option(..., help="haiku | sonnet | opus, or a full model id"),
) -> None:
    """A hand-built version that is SRC with another model (plan s08, D35 A): the same prompt
    files, `measured_against: SRC`, so the model's lift is measured apart from the prompt's."""
    from dab_bench.agent.versions import copy_with_model, load_version

    copy_with_model(src, into, model)
    v = load_version(into)
    console.print(
        f"agents/{into} · {v.config.model} · measured against {src} · fingerprint {v.fingerprint}"
    )


@app.command("split-optimise")
def split_optimise(force: bool = False) -> None:
    """Write data/splits/train.json + heldout.json from today's goldens (2/3 per dataset,
    seeded). Written once: every version is measured on the same split; --force re-draws it."""
    from dab_bench.config import SPLITS_DIR
    from dab_bench.eval import golden
    from dab_bench.eval.scorecard import write_split

    if (SPLITS_DIR / "train.json").exists() and not force:
        console.print("[yellow]the split exists[/]; --force re-draws it (and breaks comparability)")
        raise typer.Exit(1)
    s = write_split(sorted(golden.current()))
    console.print(f"train {len(s['train'])} · held-out {len(s['heldout'])}")


@app.command("isolation-check")
def isolation_check_cmd(agent: str = "champion", dataset: str = "yelp") -> None:
    """Start one session exactly as a trial would and show what the CLI gave it (one short turn)."""
    import asyncio

    from dab_bench.agent.prompt import load_context
    from dab_bench.agent.session import isolation_check
    from dab_bench.agent.versions import load_version

    out = asyncio.run(isolation_check(load_version(agent), load_context(dataset)))
    console.print_json(data=out)
    if out["problems"]:
        console.print(f"[red]not isolated[/red]: {'; '.join(out['problems'])}")
        raise typer.Exit(1)
    console.print("[green]isolated[/green]: the dab tools and the prompt, nothing else")


@app.command("golden-propose")
def golden_propose_cmd(folder: Path) -> None:
    """Load proposed golden SQL from FOLDER: one `<ds>_<n>.sql` + `<ds>_<n>.json` per question
    (json: query_id, kind, replaces, note, expected_answer). Each is run as dab_agent and judged
    before it is stored in `dataagentbench_meta.golden_proposal`. A proposal is not a golden: a
    person confirms it by saving it in the Golden tab."""
    import json

    from dab_bench.data.index import load
    from dab_bench.eval import golden

    ix = load()
    loaded = 0
    for meta_path in sorted(folder.glob("*.json")):
        meta = json.loads(meta_path.read_text())
        if not isinstance(meta, dict) or "query_id" not in meta:
            continue  # a request body or anything else that is not a proposal
        sql_path = meta_path.with_suffix(".sql")
        q = ix.query_by_id.get(meta["query_id"])
        if q is None or not sql_path.exists():
            console.print(
                f"[yellow]skip[/yellow] {meta_path.name}: no such query or no .sql beside it"
            )
            continue
        sql = sql_path.read_text()
        kind = meta.get("kind", "answer")
        folder_name = ix.dataset_by_key[q["dataset_key"]]["folder"]
        out, ex = golden.attempt(q, folder_name, sql, kind)
        saved = golden.propose(
            q["id"],
            sql,
            out,
            ex,
            replaces=str(meta.get("replaces") or ""),
            note=str(meta.get("note") or ""),
            expected_answer=str(meta.get("expected_answer") or "") if kind == "evidence" else "",
        )
        loaded += 1
        v = out["verdict"]["passed"]
        verdict = (
            "evidence"
            if kind == "evidence"
            else ("pass" if v else "fail" if v is False else "error")
        )
        console.print(
            f"#{saved['id']:<4} {q['id']:<22} {verdict:<9} {out['gold_match']['match'] or '-':<13} {ex.duration_ms:>6} ms"
        )
    console.print(f"{loaded} proposal(s) loaded; none is a golden until someone saves it")


@app.command()
def serve(port: int = 8091, host: str = "127.0.0.1", reload: bool = False) -> None:
    """Run the API (and the built explorer when frontend/dist exists)."""
    import uvicorn

    uvicorn.run(
        "dab_bench.serving.app:create_app", host=host, port=port, factory=True, reload=reload
    )


if __name__ == "__main__":
    app()
