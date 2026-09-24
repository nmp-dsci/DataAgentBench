"""Log runs and curations to the central MLflow (nmp-central-ai, http://localhost:5000).

MLflow is the index, never the record: every artifact it holds is a copy of a
file in `runs/<id>/` or `data/context/<ds>/`. The platform contract
(nmp-central-ai/PLATFORM.md): one env var `MLFLOW_TRACKING_URI`, experiment
`dataagentbench/evals`, required tags `project · git_sha · env · billing`,
fail fast when the server is down (`preflight()`), never a local store.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import mlflow

from dab_bench.config import MLFLOW_EXPERIMENT, settings

if TYPE_CHECKING:
    from dab_bench.context.curate import Curation
    from dab_bench.eval.runner import RunMeta
    from dab_bench.eval.score import TrialResult

PROJECT = "dataagentbench"


class TrackingDownError(RuntimeError):
    """The central MLflow is not reachable; the remedy is `make platform-up`."""


def preflight() -> str:
    """Curl-equivalent of `<uri>/health`; raises with the one-line remedy."""
    import urllib.error
    import urllib.request

    uri = settings().mlflow_tracking_uri.rstrip("/")
    try:
        with urllib.request.urlopen(f"{uri}/health", timeout=3) as r:  # noqa: S310 - local platform URL
            if r.status != 200:
                raise TrackingDownError(f"{uri}/health returned {r.status}")
    except (urllib.error.URLError, OSError) as e:
        raise TrackingDownError(
            f"MLflow at {uri} is not reachable ({e}). Start the platform: `make platform-up`"
        ) from e
    return uri


def _client_setup() -> None:
    mlflow.set_tracking_uri(settings().mlflow_tracking_uri)
    mlflow.set_experiment(MLFLOW_EXPERIMENT)


def _required_tags(billing: str | None = None) -> dict[str, str]:
    s = settings()
    return {
        "project": PROJECT,
        "git_sha": s.code_sha,
        "env": "local",
        "billing": billing or s.billing,
    }


def log_run(run_dir: Path, meta: RunMeta, results: list[TrialResult]) -> str:
    """One MLflow run per eval run; returns the MLflow run id."""
    _client_setup()
    s = meta.summary or {}
    with mlflow.start_run(run_name=meta.run_id) as run:
        mlflow.set_tags(
            {
                **_required_tags(),
                "agent": meta.agent,
                "fingerprint": meta.fingerprint,
                "context_sha": meta.context_sha,
                "model": meta.model,
                "effort": meta.effort,
                "split": meta.split,
                "code_sha": meta.code_sha,
                "upstream_commit": meta.upstream_commit,
                "kind": "eval",
                "challenger_of": meta.challenger_of or "",
                "hints": str(meta.hints).lower(),
                "prompt_version": str(meta.prompt_version or ""),
            }
        )
        mlflow.log_params(
            {
                "agent": meta.agent,
                "model": meta.model,
                "effort": meta.effort,
                "split": meta.split,
                "trials": meta.trials,
                "workers": meta.workers,
                "n_queries": meta.n_queries,
                "fingerprint": meta.fingerprint,
                "context_sha": meta.context_sha,
                "max_turns": meta.max_turns,
                "hints": meta.hints,
            }
        )
        metrics: dict[str, float] = {
            "cost_usd": float(s.get("cost_usd") or 0.0),
            "duration_s": float(s.get("duration_ms") or 0) / 1000,
            "errors": float(s.get("errors") or 0),
            "timeouts": float(s.get("timeouts") or 0),
            "rate_limited": float(s.get("rate_limited") or 0),
            "turns_total": float(sum(r.n_turns for r in results)),
            "input_tokens": float(sum(r.input_tokens for r in results)),
            "cache_read_tokens": float(sum(r.cache_read_tokens for r in results)),
            "cache_creation_tokens": float(sum(r.cache_creation_tokens for r in results)),
            "output_tokens": float(sum(r.output_tokens for r in results)),
        }
        if s.get("n"):
            metrics.update(
                {
                    "passed": float(s["passed"]),
                    "n": float(s["n"]),
                    "pass_rate_micro": float(s["pass_rate_micro"] or 0.0),
                    "pass_rate_macro": float(s["pass_rate_macro"] or 0.0),
                }
            )
            for ds, rate in (s.get("per_dataset") or {}).items():
                if rate.get("rate") is not None:
                    metrics[f"ds_{ds}_pass_rate"] = float(rate["rate"])
        card_path = run_dir / "scorecard.json"
        if card_path.exists():
            metrics.update(scorecard_metrics(json.loads(card_path.read_text())))
        mlflow.log_metrics(metrics)
        # per trial: pass, tokens, turns, cost; per query (mean over its trials): the same
        per_trial: dict[str, float] = {}
        by_query: dict[str, list[TrialResult]] = {}
        for r in results:
            q = r.query_id.replace("/", "_")
            key = f"q_{q}_t{r.trial}"
            if r.passed is not None:
                per_trial[key] = 1.0 if r.passed else 0.0
            per_trial[f"tokens_{key}"] = float(_total_tokens(r))
            per_trial[f"turns_{key}"] = float(r.n_turns)
            per_trial[f"cost_{key}"] = float(r.cost_usd or 0.0)
            by_query.setdefault(q, []).append(r)
        for q, rs in by_query.items():
            n = len(rs)
            per_trial[f"query_{q}_tokens"] = sum(_total_tokens(r) for r in rs) / n
            per_trial[f"query_{q}_input_tokens"] = (
                sum(r.input_tokens + r.cache_creation_tokens for r in rs) / n
            )
            per_trial[f"query_{q}_cache_read_tokens"] = sum(r.cache_read_tokens for r in rs) / n
            per_trial[f"query_{q}_output_tokens"] = sum(r.output_tokens for r in rs) / n
            per_trial[f"query_{q}_turns"] = sum(r.n_turns for r in rs) / n
            per_trial[f"query_{q}_tool_calls"] = sum(r.tool_calls for r in rs) / n
            per_trial[f"query_{q}_cost_usd"] = sum(r.cost_usd or 0.0 for r in rs) / n
            scored = [r for r in rs if r.passed is not None]
            if scored:
                per_trial[f"query_{q}_pass_rate"] = sum(1 for r in scored if r.passed) / len(scored)
        mlflow.log_metrics(per_trial)
        # the SQL-answer contract: every trial's submitted SQL, result, mode and step, as a table
        submitted = [r for r in results if r.mode]
        if submitted:
            mlflow.log_table(
                {
                    "query_id": [r.query_id for r in submitted],
                    "trial": [r.trial for r in submitted],
                    "mode": [r.mode for r in submitted],
                    "step": [r.step or "" for r in submitted],
                    "agent_sql": [r.agent_sql or "" for r in submitted],
                    "agent_result": [(r.agent_result or "")[:2000] for r in submitted],
                    "answer": [r.answer[:2000] for r in submitted],
                    "passed": [r.passed for r in submitted],
                },
                "submissions.json",
            )
        for name in ("run.json", "results.jsonl", "scorecard.json"):
            if (run_dir / name).exists():
                mlflow.log_artifact(str(run_dir / name))
        for sub in ("agent", "traces", "context"):
            if (run_dir / sub).is_dir():
                mlflow.log_artifacts(str(run_dir / sub), artifact_path=sub)
        return str(run.info.run_id)


def scorecard_metrics(card: dict[str, Any]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for col, v in (card.get("totals") or {}).items():
        metrics[f"scorecard_{col}_passed"] = float(v["passed"])
        metrics[f"scorecard_{col}_n"] = float(v["n"])
    for split, tot in (card.get("by_split") or {}).items():
        for col, v in tot.items():
            metrics[f"scorecard_{split}_{col}_passed"] = float(v["passed"])
            metrics[f"scorecard_{split}_{col}_n"] = float(v["n"])
    return metrics


def log_scorecard(mlflow_run_id: str, run_dir: Path) -> None:
    """Re-log a recomputed scorecard onto the run's existing MLflow run (`dab diagnose --refresh`)."""
    from mlflow import MlflowClient

    _client_setup()
    card = json.loads((run_dir / "scorecard.json").read_text())
    client = MlflowClient()
    for k, v in scorecard_metrics(card).items():
        client.log_metric(mlflow_run_id, k, v)
    client.log_artifact(mlflow_run_id, str(run_dir / "scorecard.json"))


def _total_tokens(r: TrialResult) -> int:
    return r.input_tokens + r.cache_read_tokens + r.cache_creation_tokens + r.output_tokens


def log_curation(cur: Curation) -> str | None:
    """A curator session as its own run, `kind=curate`, so the pack's provenance is on the server."""
    _client_setup()
    with mlflow.start_run(run_name=f"curate-{cur.dataset}") as run:
        mlflow.set_tags(
            {**_required_tags(), "kind": "curate", "dataset": cur.dataset, "model": cur.model}
        )
        mlflow.log_params({"dataset": cur.dataset, "model": cur.model})
        mlflow.log_metrics(
            {
                "cost_usd": float(cur.cost_usd or 0.0),
                "duration_s": cur.duration_ms / 1000,
                "input_tokens": float(cur.input_tokens),
                "output_tokens": float(cur.output_tokens),
                "n_turns": float(cur.n_turns),
                "error": 1.0 if cur.error else 0.0,
            }
        )
        mlflow.log_text(cur.summary, f"context/{cur.dataset}/summary.md")
        mlflow.log_text(cur.pitfalls, f"context/{cur.dataset}/pitfalls.md")
        if cur.error:
            mlflow.log_text(cur.error, "error.txt")
        return str(run.info.run_id)


def env_summary() -> dict[str, Any]:
    return {"tracking_uri": settings().mlflow_tracking_uri, "experiment": MLFLOW_EXPERIMENT}


def dump_search(path: Path) -> None:
    """`make snapshot`: the experiment's runs as JSON, for CI and the demo (sibling convention)."""
    _client_setup()
    df = mlflow.search_runs(experiment_names=[MLFLOW_EXPERIMENT])
    path.write_text(json.dumps(json.loads(df.to_json(orient="records")), indent=1))
