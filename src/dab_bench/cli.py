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
        console.print("[red]Postgres is not reachable[/] — run `make db-up` first")
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


@app.command()
def serve(port: int = 8091, host: str = "127.0.0.1", reload: bool = False) -> None:
    """Run the API (and the built explorer when frontend/dist exists)."""
    import uvicorn

    uvicorn.run(
        "dab_bench.serving.app:create_app", host=host, port=port, factory=True, reload=reload
    )


if __name__ == "__main__":
    app()
