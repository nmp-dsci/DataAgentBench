"""One MLflow trace per trial, built after the fact from the session's message stream.

`mlflow.anthropic.autolog()` sees nothing here: the model call happens inside the
`claude` CLI child the Agent SDK spawns. So the harness reconstructs the trace
with the client API and the timestamps it recorded: a root `trial` span
(inputs: question, dataset; outputs: answer, passed, reason), a `turn` child
per assistant message, a `tool` child per call with its inputs, output and
error. The tags are what the optimiser filters on (plan s01 §6):
`run_id · dataset · query · trial · passed · reason · agent · fingerprint ·
context_sha · model` plus the platform's required four.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import mlflow
from mlflow import MlflowClient

from dab_bench.config import MLFLOW_EXPERIMENT, settings
from dab_bench.tracking.mlflow_log import PROJECT

if TYPE_CHECKING:
    from dab_bench.agent.session import Solve
    from dab_bench.eval.runner import RunMeta
    from dab_bench.eval.score import TrialResult

CUT = 2_000


def _cut(v: Any, n: int = CUT) -> Any:
    if isinstance(v, str):
        return v if len(v) <= n else v[:n] + f"…[{len(v) - n} more]"
    if isinstance(v, dict):
        return {k: _cut(x, n) for k, x in v.items()}
    if isinstance(v, list):
        return [_cut(x, n) for x in v[:50]]
    return v


def emit_spans(
    client: MlflowClient, trace_id: str, parent_id: str, t0: int, entries: list[dict[str, Any]]
) -> float:
    """A `turn` child per assistant message and a `tool` child per call (its result attached by
    tool_use id), in stream order; returns the last offset in seconds. Shared by the trial trace
    and the optimiser's session trace (s13)."""
    pending: dict[str, tuple[str, int]] = {}
    last_t = 0.0
    turn_no = 0
    for entry in entries:
        role = entry.get("role")
        t = float(entry.get("t") or last_t)
        if role == "assistant":
            turn_no += 1
            blocks = entry.get("content") or []
            texts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
            uses = [b for b in blocks if b.get("type") == "tool_use"]
            turn = client.start_span(
                name=f"turn {turn_no}",
                trace_id=trace_id,
                parent_id=parent_id,
                span_type="LLM",
                inputs={"tool_results_since_last_turn": len(pending)},
                start_time_ns=t0 + int(last_t * 1e9),
            )
            client.end_span(
                trace_id=trace_id,
                span_id=turn.span_id,
                outputs={
                    "text": _cut("\n".join(texts)),
                    "tool_calls": [u.get("name") for u in uses],
                },
                end_time_ns=t0 + int(t * 1e9),
            )
            for u in uses:
                sp = client.start_span(
                    name=str(u.get("name")),
                    trace_id=trace_id,
                    parent_id=parent_id,
                    span_type="TOOL",
                    inputs=_cut(u.get("input") or {}),
                    start_time_ns=t0 + int(t * 1e9),
                )
                pending[str(u.get("id"))] = (sp.span_id, int(t * 1e9))
            last_t = t
        elif role == "tool":
            for b in entry.get("content") or []:
                if b.get("type") != "tool_result":
                    continue
                span = pending.pop(str(b.get("tool_use_id")), None)
                if span is None:
                    continue
                client.end_span(
                    trace_id=trace_id,
                    span_id=span[0],
                    outputs={"result": _cut(str(b.get("content") or ""))},
                    status="ERROR" if b.get("is_error") else "OK",
                    end_time_ns=t0 + int(t * 1e9),
                )
            last_t = t
    for span_id, _ in pending.values():
        client.end_span(
            trace_id=trace_id, span_id=span_id, status="ERROR", end_time_ns=t0 + int(last_t * 1e9)
        )
    return last_t


def log_trial_trace(
    meta: RunMeta, result: TrialResult, solve: Solve, started_at_s: float
) -> str | None:
    """Build and log the trace; returns the trace id, or None when tracking is unreachable."""
    s = settings()
    mlflow.set_tracking_uri(s.mlflow_tracking_uri)
    exp = mlflow.set_experiment(MLFLOW_EXPERIMENT)
    client = MlflowClient()
    t0 = int(started_at_s * 1e9)
    tags = {
        "project": PROJECT,
        "git_sha": s.code_sha,
        "env": "local",
        "billing": s.billing,
        "run_id": meta.run_id,
        "dataset": result.dataset,
        "query": result.query_id,
        "trial": str(result.trial),
        "passed": "" if result.passed is None else str(int(result.passed)),
        "reason": (result.reason or "")[:250],
        "agent": meta.agent,
        "fingerprint": meta.fingerprint,
        "context_sha": meta.context_sha,
        "model": meta.model,
        "effort": meta.effort,
        "kind": "trial",
    }
    if result.mode:
        tags["mode"] = result.mode  # the SQL-answer contract: pass_through | derived
    root = client.start_trace(
        name=f"{result.query_id} t{result.trial}",
        span_type="AGENT",
        inputs={"question": result.question, "dataset": result.dataset},
        attributes={
            "agent": meta.agent,
            "fingerprint": meta.fingerprint,
            "context_sha": meta.context_sha,
            "model": meta.model,
            "system_prompt_chars": str(solve.system_prompt_chars),
        },
        tags=tags,
        experiment_id=exp.experiment_id,
        start_time_ns=t0,
    )
    trace_id = root.trace_id
    last_t = emit_spans(client, trace_id, root.span_id, t0, solve.trace)
    client.end_trace(
        trace_id=trace_id,
        outputs={"answer": _cut(result.answer), "passed": result.passed, "reason": result.reason}
        | (
            {
                "agent_sql": _cut(result.agent_sql or ""),
                "agent_result": _cut(result.agent_result or ""),
                "mode": result.mode,
                "step": result.step or "",
            }
            | ({"plan": result.plan} if result.plan else {})
            if result.mode
            else {}
        ),
        attributes={
            # the standard key the Traces tab reads for its Tokens column (what autologgers set)
            "mlflow.chat.tokenUsage": {
                "input_tokens": result.input_tokens
                + result.cache_read_tokens
                + result.cache_creation_tokens,
                "output_tokens": result.output_tokens,
                "total_tokens": result.input_tokens
                + result.cache_read_tokens
                + result.cache_creation_tokens
                + result.output_tokens,
            },
            "n_turns": result.n_turns,
            "tool_calls": result.tool_calls,
            "input_tokens": result.input_tokens,
            "cache_read_tokens": result.cache_read_tokens,
            "cache_creation_tokens": result.cache_creation_tokens,
            "output_tokens": result.output_tokens,
            "cost_usd": result.cost_usd or 0.0,
            "error": result.error or "",
        },
        status="ERROR" if result.error else "OK",
        end_time_ns=t0 + int(max(last_t, result.duration_ms / 1000) * 1e9),
    )
    return str(trace_id)


def flush() -> None:
    import contextlib

    with contextlib.suppress(Exception):
        mlflow.flush_trace_async_logging()


def now_s() -> float:
    return time.time()


# ── the optimiser's sessions (s13, B3) ───────────────────────────────────────


def log_session_trace(record: dict[str, Any], session: dict[str, Any], started_at_s: float) -> str:
    """One optimiser session as a trace, `kind=optimise_session`: the briefing it read, a span
    per turn and tool call, and what it wrote, its refusals and G1's verdicts. Tagged with its
    round (version, parent, source run, the round's MLflow run) so a later round's history and
    the Traces tab can find it."""
    s = settings()
    mlflow.set_tracking_uri(s.mlflow_tracking_uri)
    exp = mlflow.set_experiment(MLFLOW_EXPERIMENT)
    client = MlflowClient()
    t0 = int(started_at_s * 1e9)
    trace = session.get("trace") or []
    briefing = next((str(e.get("content") or "") for e in trace if e.get("role") == "user"), "")
    reviews = session.get("reviews") or []
    refusals = session.get("refusals") or []
    root = client.start_trace(
        name=f"optimise {record['version']} {session['scope']}",
        span_type="AGENT",
        inputs={
            "scope": session["scope"],
            "questions": session.get("questions") or [],
            "briefing": _cut(briefing, 20_000),
        },
        tags={
            "project": PROJECT,
            "git_sha": s.code_sha,
            "env": "local",
            "billing": s.billing,
            "kind": "optimise_session",
            "agent": record["version"],
            "challenger_of": record.get("challenger_of") or "",
            "source_run": record.get("source_run") or "",
            "optimise_run": record.get("mlflow_run_id") or "",
            "scope": session["scope"],
            "session_kind": session.get("kind") or "dataset",
            "accepted": "1" if session.get("notes") is not None else "0",
            "dropped": "1" if session.get("dropped") else "0",
            "refusals": str(len(refusals)),
            "g1_decisive": str(sum(1 for r in reviews if r.get("decisive"))),
            "model": str((record.get("optimiser") or {}).get("model") or ""),
        },
        experiment_id=exp.experiment_id,
        start_time_ns=t0,
    )
    last_t = emit_spans(client, root.trace_id, root.span_id, t0, trace)
    client.end_trace(
        trace_id=root.trace_id,
        outputs={
            "notes": session.get("notes"),
            "rationale": session.get("rationale") or "",
            "refusals": [r.get("problems") for r in refusals],
            "reviews": [
                {k: r.get(k) for k in ("decisive", "question", "what", "reviewed")} for r in reviews
            ],
        },
        attributes={
            "cost_usd": session.get("cost_usd") or 0.0,
            "n_turns": session.get("n_turns") or 0,
            "input_tokens": session.get("input_tokens") or 0,
            "output_tokens": session.get("output_tokens") or 0,
            "error": session.get("error") or "",
        },
        status="ERROR" if session.get("error") else "OK",
        end_time_ns=t0 + int(max(last_t, (session.get("duration_ms") or 0) / 1000) * 1e9),
    )
    return str(root.trace_id)


def session_traces(version: str) -> int:
    """How many optimiser-session traces MLflow holds for the round that wrote `version`."""
    mlflow.set_tracking_uri(settings().mlflow_tracking_uri)
    exp = mlflow.set_experiment(MLFLOW_EXPERIMENT)
    found = mlflow.search_traces(
        locations=[exp.experiment_id],
        filter_string=f"tags.kind = 'optimise_session' and tags.agent = '{version}'",
        max_results=100,
        return_type="list",
    )
    return len(found)


def log_round_sessions(record: dict[str, Any], session_dir: Path, force: bool = False) -> int:
    """Every session file of a round (`runs/<run>/optimise/<version>/*.json`) as a trace; a round
    already traced is skipped unless `force`. Returns how many were logged."""
    import json
    from datetime import datetime

    if not force and session_traces(record["version"]):
        return 0
    started = datetime.fromisoformat(str(record["started_at"])).timestamp()
    n = 0
    for f in sorted(session_dir.glob("*.json")):
        sess = json.loads(f.read_text())
        if not isinstance(sess, dict) or "scope" not in sess or "trace" not in sess:
            continue  # e.g. the G1 audit of the inherited text: not a session
        log_session_trace(record, sess, started)
        n += 1
    flush()
    return n
