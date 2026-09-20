"""`dab` — the command line behind every Makefile target."""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


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


@app.command()
def serve(port: int = 8091, host: str = "127.0.0.1", reload: bool = False) -> None:
    """Run the API (and the built explorer when frontend/dist exists)."""
    import uvicorn

    uvicorn.run(
        "dab_bench.serving.app:create_app", host=host, port=port, factory=True, reload=reload
    )


if __name__ == "__main__":
    app()
