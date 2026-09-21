"""The API behind the explorer, and the explorer itself when a build is present.

Every route serves committed files — the index under `data/index/`, the
answers under `data/answers/`, the context pack under `data/context/` — plus
this machine's run folders under `runs/`. Nothing here reads the upstream
clone, calls a model, or writes; MLflow is linked, never read.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from dab_bench import __version__
from dab_bench.config import CONTEXT_DIR, FRONTEND_DIST, RUNS_DIR, settings
from dab_bench.data.index import Index, load, stats

EXAMPLES_PER_FILE = 3


def create_app(index: Index | None = None) -> FastAPI:
    app = FastAPI(title="dab-bench", version=__version__)
    s = settings()
    ix = index or load()

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "code_sha": s.code_sha,
            "source": {k: ix.source[k] for k in ("repo", "commit", "ingested_at")},
            "rescored": ix.trials is not None,
        }

    @app.get("/api/source")
    def source() -> dict[str, Any]:
        return ix.source

    @app.get("/api/stats")
    def api_stats() -> dict[str, Any]:
        return stats(ix)

    # ── datasets ──────────────────────────────────────────────────────────
    @app.get("/api/datasets")
    def datasets() -> list[dict[str, Any]]:
        return [_dataset_summary(ix, d) for d in ix.datasets]

    @app.get("/api/datasets/{key}")
    def dataset(key: str) -> dict[str, Any]:
        d = ix.dataset_by_key.get(key)
        if d is None:
            raise HTTPException(404, f"no dataset {key!r} in the index")
        return {
            **d,
            "trials": _dataset_trials(ix, key),
            "query_rows": [_query_summary(ix, ix.query_by_id[q]) for q in d["queries"]],
        }

    # ── queries ───────────────────────────────────────────────────────────
    @app.get("/api/queries")
    def queries() -> list[dict[str, Any]]:
        return [_query_summary(ix, q) for q in ix.queries]

    @app.get("/api/queries/{key}/{n}")
    def query(key: str, n: int) -> dict[str, Any]:
        q = ix.query_by_id.get(f"{key}/{n}")
        if q is None:
            raise HTTPException(404, f"no query {key}/{n} in the index")
        d = ix.dataset_by_key[q["dataset_key"]]
        return {
            **q,
            "dataset": _dataset_summary(ix, d),
            "hints": d["hints"],
            "trials": _query_trials(ix, q["id"]),
        }

    # ── validators, leaderboard, trials ───────────────────────────────────
    @app.get("/api/validators")
    def validators() -> dict[str, Any]:
        rows = []
        for st in ix.validators["styles"]:
            ids = st["ids"]
            passed = n = 0
            for qid in ids:
                t = ix.query_trials(qid)
                if t:
                    passed += t["passed"]
                    n += t["n"]
            rows.append({**st, "trials": {"n": n, "passed": passed} if n else None})
        return {**ix.validators, "styles": rows}

    @app.get("/api/leaderboard")
    def leaderboard() -> dict[str, Any]:
        return ix.leaderboard

    @app.get("/api/trials")
    def trials() -> dict[str, Any]:
        if ix.trials is None:
            raise HTTPException(404, "not rescored yet; run `make rescore`")
        return {k: v for k, v in ix.trials.items() if k != "per_query"}

    # ── runs: our own evals, read from runs/<id>/ on disk (never from MLflow) ─────

    @app.get("/api/runs")
    def runs() -> list[dict[str, Any]]:
        from dab_bench.eval.runner import list_runs

        return [_run_summary(asdict(m)) for m in reversed(list_runs())]

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str) -> dict[str, Any]:
        from dab_bench.eval.runner import load_run

        if not (RUNS_DIR / run_id / "run.json").exists():
            raise HTTPException(404, f"no run {run_id}")
        meta, results = load_run(run_id)
        d = asdict(meta) | _run_summary(asdict(meta))
        d["results"] = [r.as_dict() for r in results]
        for r in d["results"]:
            r["mlflow_trace_url"] = _mlflow_trace_url(r.get("mlflow_trace_id"))
        return d

    @app.get("/api/runs/{run_id}/traces/{key}")
    def run_trace(run_id: str, key: str) -> dict[str, Any]:
        p = RUNS_DIR / run_id / "traces" / f"{key}.json"
        if not p.exists():
            raise HTTPException(404, f"no trace {key} in {run_id}")
        return json.loads(p.read_text())  # type: ignore[no-any-return]

    @app.get("/api/context/{key}")
    def context_pack(key: str) -> dict[str, Any]:
        d = CONTEXT_DIR / key
        if not d.is_dir():
            raise HTTPException(404, f"no context pack for {key}")
        files = {}
        for name in (
            "summary.md",
            "pitfalls.md",
            "schema.md",
            "joins.md",
            "description.txt",
            "hints.txt",
        ):
            if (d / name).exists():
                files[name] = (d / name).read_text()
        cur = (
            json.loads((d / "curation.json").read_text())
            if (d / "curation.json").exists()
            else None
        )
        return {"dataset": key, "files": files, "curation": cur}

    _mount_frontend(app)
    return app


def _mlflow_run_url(run_id: str | None) -> str | None:
    if not run_id:
        return None
    return f"{settings().mlflow_tracking_uri.rstrip('/')}/#/experiments/search?runId={run_id}"


def _mlflow_trace_url(trace_id: str | None) -> str | None:
    if not trace_id:
        return None
    return f"{settings().mlflow_tracking_uri.rstrip('/')}/#/traces/{trace_id}"


def _run_summary(d: dict[str, Any]) -> dict[str, Any]:
    s = d.get("summary") or {}
    return {
        k: d.get(k)
        for k in (
            "run_id",
            "agent",
            "fingerprint",
            "context_sha",
            "model",
            "effort",
            "split",
            "n_queries",
            "trials",
            "hints",
            "dry_run",
            "started_at",
            "finished_at",
            "note",
            "kind",
            "challenger_of",
            "mlflow_run_id",
        )
    } | {
        "passed": s.get("passed"),
        "scored": s.get("scored"),
        "n": s.get("n"),
        "pass_rate_macro": s.get("pass_rate_macro"),
        "pass_rate_micro": s.get("pass_rate_micro"),
        "cost_usd": s.get("cost_usd"),
        "duration_ms": s.get("duration_ms"),
        "errors": s.get("errors"),
        "timeouts": s.get("timeouts"),
        "per_dataset": s.get("per_dataset"),
        "mlflow_url": _mlflow_run_url(d.get("mlflow_run_id")),
    }


# ── shaping ───────────────────────────────────────────────────────────────


def _dataset_trials(ix: Index, key: str) -> dict[str, Any] | None:
    if ix.trials is None:
        return None
    qs = ix.dataset_by_key[key]["queries"]
    n = passed = 0
    for qid in qs:
        t = ix.query_trials(qid)
        if t:
            n += t["n"]
            passed += t["passed"]
    if not n:
        return None
    return {"n": n, "passed": passed, "rate": passed / n}


def _dataset_summary(ix: Index, d: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": d["key"],
        "folder": d["folder"],
        "n_queries": d["n_queries"],
        "queries": d["queries"],
        "engines": d["engines"],
        "n_dbs": d["n_dbs"],
        "bytes_total": d["bytes_total"],
        "description_bytes": d["description_bytes"],
        "hints_bytes": d["hints_bytes"],
        "trials": _dataset_trials(ix, d["key"]),
    }


def _query_summary(ix: Index, q: dict[str, Any]) -> dict[str, Any]:
    t = ix.query_trials(q["id"])
    best = None
    if t:
        best = max(
            ((f["passed"] / f["n"], name) for name, f in t["files"].items() if f["n"]), default=None
        )
    return {
        "id": q["id"],
        "dataset_key": q["dataset_key"],
        "query_id": q["query_id"],
        "question": q["question"],
        "gold_lines": q["gold_lines"],
        "gold_preview": q["gold_text"][:120],
        "validator_style": q["validator"]["style"],
        "validator_lines": q["validator"]["lines"],
        "footnote": q["footnote"],
        "site_text_matches": q["site_text_matches"],
        "trials": {
            "n": t["n"],
            "passed": t["passed"],
            "rate": t["passed"] / t["n"] if t["n"] else None,
            "timed_out": t["timed_out"],
            "best_file": best[1] if best else None,
            "best_rate": best[0] if best else None,
        }
        if t
        else None,
    }


def _query_trials(ix: Index, qid: str) -> dict[str, Any] | None:
    """Per answer file: counts plus the example rows resolved to their answers."""
    t = ix.query_trials(qid)
    rows_by_file = ix.answers.get(qid, {})
    files_meta = {f["name"]: f for f in ix.leaderboard.get("answer_files", [])}
    if t is None:
        if not rows_by_file:
            return None
        return {
            "rescored": False,
            "n": sum(len(r) for r in rows_by_file.values()),
            "files": [
                {
                    "name": name,
                    "label": files_meta.get(name, {}).get("label", name),
                    "rank": files_meta.get(name, {}).get("rank"),
                    "n": len(rows),
                }
                for name, rows in rows_by_file.items()
            ],
        }
    out = []
    for name, f in t["files"].items():
        rows = rows_by_file.get(name, [])
        by_i = {r["i"]: r for r in rows}
        out.append(
            {
                "name": name,
                "label": files_meta.get(name, {}).get("label", name),
                "rank": files_meta.get(name, {}).get("rank"),
                "n": f["n"],
                "passed": f["passed"],
                "timed_out": f["timed_out"],
                "passes": [
                    {"run": by_i[i]["run"], "answer": by_i[i]["answer"]}
                    for i in f["pass_examples"]
                    if i in by_i
                ],
                "fails": [
                    {
                        "run": by_i[e["i"]]["run"],
                        "answer": by_i[e["i"]]["answer"],
                        "reason": e["reason"],
                    }
                    for e in f["fail_examples"]
                    if e["i"] in by_i
                ],
            }
        )
    return {
        "rescored": True,
        "n": t["n"],
        "passed": t["passed"],
        "timed_out": t["timed_out"],
        "files": out,
    }


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built SPA from this process when `frontend/dist` exists (absent in dev: Vite serves it)."""
    if not FRONTEND_DIST.is_dir():
        return
    assets = FRONTEND_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
    index = FRONTEND_DIST / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str, request: Request) -> Any:
        if path.startswith("api/"):
            raise HTTPException(404)
        candidate = (FRONTEND_DIST / path).resolve()
        if path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)
