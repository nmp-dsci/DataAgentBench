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
        mlflow.log_metrics(metrics)
        for r in results:
            if r.passed is not None:
                mlflow.log_metric(
                    f"q_{r.query_id.replace('/', '_')}_t{r.trial}", 1.0 if r.passed else 0.0
                )
        for name in ("run.json", "results.jsonl"):
            if (run_dir / name).exists():
                mlflow.log_artifact(str(run_dir / name))
        for sub in ("agent", "traces", "context"):
            if (run_dir / sub).is_dir():
                mlflow.log_artifacts(str(run_dir / sub), artifact_path=sub)
        return str(run.info.run_id)


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
