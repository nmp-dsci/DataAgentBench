"""The API behind the explorer, and the explorer itself when a build is present.

Every route serves the committed index under `data/index/` and `data/answers/`.
Nothing here reads the upstream clone, calls a model, or writes.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from dab_bench import __version__
from dab_bench.config import FRONTEND_DIST, settings
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

    _mount_frontend(app)
    return app


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
