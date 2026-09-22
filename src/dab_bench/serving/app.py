"""The API behind the explorer, and the explorer itself when a build is present.

Every route serves committed files — the index under `data/index/`, the
answers under `data/answers/`, the context pack under `data/context/`, the
agent versions under `agents/` — plus this machine's run folders under `runs/`.
Nothing here reads the upstream clone or calls a model; MLflow is linked, never
read. The one route that executes is the playground, `POST /api/agent/tools/<name>`:
the trial's own tool bodies on the read-only role and the network-off sandbox,
writing nothing but /work files under `workspace/playground_*`.
"""

from __future__ import annotations

import functools
import json
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from dab_bench import __version__
from dab_bench.config import (
    CONTEXT_DIR,
    FRONTEND_DIST,
    MLFLOW_EXPERIMENT,
    RUNS_DIR,
    WORKSPACE_DIR,
    settings,
)
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
    def runs() -> dict[str, Any]:
        """Every run folder with its role (champion, challenger, superseded, smoke, dry) and
        its per-trial profile. The champion is derived: the newest scored full-split run of
        the agent `agents/champion` names that is not itself a challenger."""
        return _board()

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str) -> dict[str, Any]:
        from dab_bench.eval.runner import load_run

        if not (RUNS_DIR / run_id / "run.json").exists():
            raise HTTPException(404, f"no run {run_id}")
        board = _board()
        row = next((r for r in board["runs"] if r["run_id"] == run_id), None)
        meta, results = load_run(run_id)
        d = asdict(meta) | (row or _run_summary(asdict(meta)))
        d["results"] = [r.as_dict() for r in results]
        for r in d["results"]:
            r["mlflow_trace_url"] = _mlflow_trace_url(r.get("mlflow_trace_id"))
        champ = board["champion_run_id"]
        d["versus"] = (
            next((r for r in board["runs"] if r["run_id"] == champ), None)
            if champ and champ != run_id
            else None
        )
        return d

    @app.get("/api/runs/{run_id}/traces/{key}")
    def run_trace(run_id: str, key: str) -> dict[str, Any]:
        from dab_bench.eval.runner import load_run

        p = RUNS_DIR / run_id / "traces" / f"{key}.json"
        if not p.exists():
            raise HTTPException(404, f"no trace {key} in {run_id}")
        t: dict[str, Any] = json.loads(p.read_text())
        # the verdict and the MLflow link live on the result row, not in the trace file
        _, results = load_run(run_id)
        row = next((r for r in results if r.trace_file == f"traces/{key}.json"), None)
        t["passed"] = row.passed if row else None
        t["reason"] = row.reason if row else ""
        t["mlflow_trace_id"] = row.mlflow_trace_id if row else None
        t["mlflow_trace_url"] = _mlflow_trace_url(row.mlflow_trace_id) if row else None
        t["mlflow_embeddable"] = _mlflow_embeddable()
        t["spans"] = _spans(t)
        return t

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

    # ── the agent: versions, the composed prompt, and the playground ─────────────

    @app.get("/api/agents")
    def agents() -> dict[str, Any]:
        from dab_bench.agent.versions import champion_name, list_versions, load_version

        out = []
        for name in list_versions():
            v = load_version(name)
            out.append(
                {
                    "name": name,
                    "fingerprint": v.fingerprint,
                    "model": v.config.model,
                    "effort": v.config.effort,
                    "max_turns": v.config.max_turns,
                    "timeout_s": v.config.timeout_s,
                    "exec_timeout_s": v.config.exec_timeout_s,
                    "hints": v.config.hints,
                    "tools": [t.replace("mcp__dab__", "") for t in v.config.tools],
                }
            )
        return {"champion": champion_name(), "versions": out}

    @app.get("/api/agents/{name}")
    def agent_detail(name: str) -> dict[str, Any]:
        from dab_bench.agent.sandbox import image_exists
        from dab_bench.agent.tools import TOOL_SPECS
        from dab_bench.agent.versions import champion_name

        v = _version(name)
        allowed = [t.replace("mcp__dab__", "") for t in v.config.tools]
        return {
            "name": v.name,
            "champion": v.name == champion_name(),
            "fingerprint": v.fingerprint,
            "config": asdict(v.config),
            "files": v.files(),
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "schema": t.schema,
                    "backend": t.backend,
                    "calls_model": t.calls_model,
                    "playground": "off"
                    if t.calls_model and not s.playground_llm
                    else "echo"
                    if t.name == "return_answer"
                    else "on",
                }
                for t in TOOL_SPECS.values()
                if t.name in allowed
            ],
            "sandbox_built": image_exists(),
            "playground_llm": s.playground_llm,
            "datasets": sorted(
                p.name for p in CONTEXT_DIR.iterdir() if (p / "tables.json").exists()
            )
            if CONTEXT_DIR.exists()
            else [],
        }

    @app.get("/api/agents/{name}/prompt")
    def agent_prompt(name: str, dataset: str, hints: bool = False) -> dict[str, Any]:
        from dab_bench.agent.prompt import compose_system_prompt, load_context

        v = _version(name)
        try:
            ctx = load_context(dataset)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e
        prompt = compose_system_prompt(v.system_prompt, ctx, hints=hints)
        return {
            "agent": v.name,
            "dataset": dataset,
            "context_sha": ctx.context_sha,
            "chars": len(prompt),
            "prompt": prompt,
        }

    @app.post("/api/agent/tools/{name}")
    def playground(name: str, body: ToolCall) -> dict[str, Any]:
        """Run one tool by hand with the trial's own guards. Not a trial: no run folder,
        no MLflow trace; only /work files under workspace/playground_<dataset>."""
        from dab_bench.agent.prompt import load_context
        from dab_bench.agent.sandbox import image_exists
        from dab_bench.agent.tools import TOOL_SPECS, ToolState, call_tool

        v = _version(body.agent)
        spec = TOOL_SPECS.get(name)
        if spec is None or f"mcp__dab__{name}" not in v.config.tools:
            raise HTTPException(400, f"no tool {name!r} on agent {v.name}")
        if spec.calls_model:
            if not s.playground_llm:
                raise HTTPException(
                    403, "llm_extract calls a model; set DAB_PLAYGROUND_LLM=1 to allow it here"
                )
            raise HTTPException(501, "llm_extract in the playground is not wired yet (D8-A)")
        missing = [k for k in spec.schema.get("required", []) if body.input.get(k) in (None, "")]
        if missing:
            raise HTTPException(400, f"missing input: {', '.join(missing)}")
        try:
            ctx = load_context(body.dataset)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e
        sandbox = None
        if spec.backend == "sandbox":
            if not image_exists():
                raise HTTPException(503, "sandbox image missing: run `make sandbox`")
            sandbox = _playground_sandbox()
        elif name == "query_db" and body.input.get("save_as"):
            sandbox = _playground_sandbox() if image_exists() else None
        state = ToolState(
            dataset=body.dataset,
            ctx=ctx,
            trial_key=f"playground_{body.dataset}",
            sandbox=sandbox,
            exec_timeout_s=v.config.exec_timeout_s,
        )
        out, err = call_tool(state, name, body.input)
        call = state.calls[-1]
        return {
            "tool": name,
            "dataset": body.dataset,
            "input": call["input"],
            "output": out,
            "chars": call["chars"],
            "cut": call["chars"] > len(out),
            "elapsed_s": call["elapsed_s"],
            "error": err,
        }

    @app.on_event("shutdown")
    def _stop_sandbox() -> None:
        sb = _PLAYGROUND.get("sandbox")
        if sb is not None:
            sb.stop()

    _mount_frontend(app)
    return app


class ToolCall(BaseModel):
    agent: str = "champion"
    dataset: str
    input: dict[str, Any] = {}


_PLAYGROUND: dict[str, Any] = {}


def _playground_sandbox() -> Any:
    """One container for the explorer process, started on first use; /work is
    workspace/playground/ so a query_db(save_as) here is readable by execute_python here."""
    from dab_bench.agent.sandbox import Sandbox

    if _PLAYGROUND.get("sandbox") is None:
        _PLAYGROUND["sandbox"] = Sandbox.start("playground", WORKSPACE_DIR / "playground")
    return _PLAYGROUND["sandbox"]


def _version(name: str) -> Any:
    from dab_bench.agent.versions import load_version

    try:
        return load_version(name)
    except FileNotFoundError as e:
        raise HTTPException(404, f"no agent version {name!r}") from e


def _mlflow_run_url(run_id: str | None) -> str | None:
    if not run_id:
        return None
    return f"{settings().mlflow_tracking_uri.rstrip('/')}/#/experiments/search?runId={run_id}"


@functools.lru_cache(maxsize=1)
def _mlflow_embeddable() -> bool:
    """Whether the central MLflow UI can be framed by the explorer: its server sends
    `X-Frame-Options: SAMEORIGIN` unless started with MLFLOW_SERVER_X_FRAME_OPTIONS=NONE.
    One HEAD request, cached for the life of the process; unreachable means no."""
    import urllib.request

    try:
        req = urllib.request.Request(settings().mlflow_tracking_uri, method="HEAD")
        with urllib.request.urlopen(req, timeout=2) as r:  # noqa: S310 - configured tracking URI
            return r.headers.get("X-Frame-Options", "").upper() in ("", "NONE")
    except Exception:
        return False


@functools.lru_cache(maxsize=1)
def _mlflow_experiment_id() -> str | None:
    """The experiment's id, which the MLflow 3 UI needs in a trace link
    (`#/experiments/<id>/traces?traceId=…`; `#/traces/<id>` is a 404).
    One metadata call, cached per process; None when tracking is unreachable."""
    import urllib.parse
    import urllib.request

    url = (
        settings().mlflow_tracking_uri.rstrip("/")
        + "/api/2.0/mlflow/experiments/get-by-name?"
        + urllib.parse.urlencode({"experiment_name": MLFLOW_EXPERIMENT})
    )
    try:
        with urllib.request.urlopen(url, timeout=2) as r:  # noqa: S310 - configured tracking URI
            return str(json.load(r)["experiment"]["experiment_id"])
    except Exception:
        return None


def _mlflow_trace_url(trace_id: str | None) -> str | None:
    if not trace_id:
        return None
    base = settings().mlflow_tracking_uri.rstrip("/")
    exp = _mlflow_experiment_id()
    if exp is None:
        return f"{base}/#/experiments/search?searchFilter=tags.run_id&traceId={trace_id}"
    return f"{base}/#/experiments/{exp}/traces?traceId={trace_id}"


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


def _board() -> dict[str, Any]:
    """The runs list with roles. Read from disk on every call: five folders, tiny files."""
    from dab_bench.agent.versions import champion_name
    from dab_bench.eval.runner import list_runs, load_run
    from dab_bench.eval.score import profile

    champion = champion_name()
    rows = []
    for m in reversed(list_runs()):
        _, results = load_run(m.run_id)
        rows.append(_run_summary(asdict(m)) | {"profile": profile(results)})
    full = [r for r in rows if r["split"] == "all" and not r["dry_run"] and (r["scored"] or 0) > 0]
    champ = next(
        (r for r in full if r["agent"] == champion and not r["challenger_of"]), None
    )  # rows are newest first
    for r in rows:
        if r["dry_run"]:
            r["role"] = "dry"
        elif r["split"] != "all":
            r["role"] = "smoke"
        elif champ and r["run_id"] == champ["run_id"]:
            r["role"] = "champion"
        elif r["agent"] == champion and not r["challenger_of"]:
            r["role"] = "superseded"
        else:
            r["role"] = "challenger"
    return {
        "champion": champion,
        "champion_run_id": champ["run_id"] if champ else None,
        "runs": rows,
    }


def _spans(t: dict[str, Any]) -> list[dict[str, Any]]:
    """The trial as the span tree `tracking/tracing.py` logs to MLflow, from the same stream:
    one `turn` span per assistant message, one tool span per call, timed by the recorded
    offsets. The explorer draws this; MLflow is never read back."""
    spans: list[dict[str, Any]] = []
    pending: dict[str, int] = {}
    last_t = 0.0
    turn_no = 0
    for entry in t.get("trace") or []:
        role = entry.get("role")
        tt = float(entry.get("t") or last_t)
        content = entry.get("content") or []
        if role == "assistant" and isinstance(content, list):
            turn_no += 1
            texts = [b.get("text", "") for b in content if b.get("type") == "text"]
            thinking = sum(
                len(b.get("thinking", "")) for b in content if b.get("type") == "thinking"
            )
            uses = [b for b in content if b.get("type") == "tool_use"]
            spans.append(
                {
                    "kind": "turn",
                    "name": f"turn {turn_no}",
                    "start": last_t,
                    "end": tt,
                    "status": "OK",
                    "text": "\n".join(texts),
                    "thinking_chars": thinking,
                    "tool_calls": [u.get("name") for u in uses],
                }
            )
            for u in uses:
                pending[str(u.get("id"))] = len(spans)
                spans.append(
                    {
                        "kind": "tool",
                        "name": str(u.get("name") or "").replace("mcp__dab__", ""),
                        "start": tt,
                        "end": None,
                        "status": "OK",
                        "input": u.get("input") or {},
                        "output": "",
                    }
                )
            last_t = tt
        elif role == "tool" and isinstance(content, list):
            for b in content:
                if b.get("type") != "tool_result":
                    continue
                i = pending.pop(str(b.get("tool_use_id")), None)
                if i is None:
                    continue
                spans[i]["end"] = tt
                spans[i]["output"] = str(b.get("content") or "")
                spans[i]["status"] = "ERROR" if b.get("is_error") else "OK"
            last_t = tt
    for i in pending.values():
        spans[i]["end"] = last_t
        spans[i]["status"] = "ERROR"
    return spans


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
