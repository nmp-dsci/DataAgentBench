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
    # turns and tools, in stream order; tool results attach to the preceding tool_use by id
    pending: dict[str, tuple[str, int]] = {}
    last_t = 0.0
    turn_no = 0
    for entry in solve.trace:
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
                parent_id=root.span_id,
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
                    parent_id=root.span_id,
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
