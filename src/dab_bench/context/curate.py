"""`dab context curate`: the curator agent writes `summary.md` and `pitfalls.md` for one dataset.

One Agent SDK session per dataset, no tools, one turn: the system prompt is
`agents/curator/system.md`, the user message is the generated pack (schema,
profile, samples, joins, description, hints). The curator never sees a
question — its inputs are the rubric's own legitimate ones — and
`tests/test_context.py` asserts no query text lands in its output. Every
session is traced to MLflow as `kind=curate` when tracking is reachable.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dab_bench.agent.llm import EFFORT, require_live, resolve_model, subscription_env
from dab_bench.agent.versions import AgentConfig, AgentVersion, load_version
from dab_bench.config import CONTEXT_DIR, ROOT

MARK_SUMMARY = "=== summary.md ==="
MARK_PITFALLS = "=== pitfalls.md ==="
PROFILE_CHARS = 60_000
SAMPLES_CHARS = 40_000


@dataclass
class Curation:
    dataset: str
    summary: str
    pitfalls: str
    n_turns: int
    duration_ms: int
    cost_usd: float | None
    input_tokens: int
    output_tokens: int
    model: str
    error: str | None = None


def pack_message(dataset: str, context_dir: Path = CONTEXT_DIR) -> str:
    d = context_dir / dataset

    def read(name: str, cap: int | None = None) -> str:
        p = d / name
        if not p.exists():
            return "(missing)"
        t = p.read_text()
        return t if cap is None or len(t) <= cap else t[:cap] + f"\n…[cut at {cap} chars]"

    profile = json.loads(read("profile.json")) if (d / "profile.json").exists() else {}
    # trim the profile so the largest datasets still fit: keep types, nulls, distinct, min/max, top values
    slim: dict[str, Any] = {}
    for table, cols in profile.items():
        slim[table] = {}
        for c, e in cols.items():
            keep = {
                k: v
                for k, v in e.items()
                if k in ("type", "null_rate", "distinct", "min", "max", "top", "sampled")
            }
            if "json_keys" in e:
                keep["json_keys"] = list(e["json_keys"])[:15]
            slim[table][c] = keep
    profile_text = json.dumps(slim, ensure_ascii=False)
    if len(profile_text) > PROFILE_CHARS:
        profile_text = profile_text[:PROFILE_CHARS] + "\n…[cut]"
    samples = (
        "\n\n".join(p.read_text() for p in sorted((d / "samples").glob("*.md")))
        if (d / "samples").is_dir()
        else "(missing)"
    )
    if len(samples) > SAMPLES_CHARS:
        samples = samples[:SAMPLES_CHARS] + "\n…[cut]"
    return "\n\n".join(
        [
            f"# Dataset: {dataset}",
            "## schema.md\n" + read("schema.md"),
            "## profile.json (per column)\n```json\n" + profile_text + "\n```",
            "## samples\n" + samples,
            "## joins.md\n" + read("joins.md"),
            "## description.txt (upstream)\n" + read("description.txt"),
            "## hints.txt (upstream)\n" + read("hints.txt"),
            "Write the two files now.",
        ]
    )


def split_output(text: str) -> tuple[str, str]:
    """The two files from the curator's final text; empty strings when a marker is missing."""
    s = text.find(MARK_SUMMARY)
    p = text.find(MARK_PITFALLS)
    if s < 0 or p < 0 or p < s:
        return "", ""
    summary = text[s + len(MARK_SUMMARY) : p].strip()
    pitfalls = text[p + len(MARK_PITFALLS) :].strip()
    pitfalls = re.sub(r"\n=== .* ===\s*$", "", pitfalls).strip()
    return summary + "\n", pitfalls + "\n"


async def curate_dataset(
    dataset: str,
    version: AgentVersion | None = None,
    model: str | None = None,
    context_dir: Path = CONTEXT_DIR,
) -> Curation:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        TextBlock,
    )

    require_live()
    version = version or load_version("curator")
    cfg: AgentConfig = version.config
    model_id = resolve_model(model or cfg.model)
    options = ClaudeAgentOptions(
        system_prompt=version.system_prompt,
        model=model_id,
        tools=[],
        allowed_tools=[],
        permission_mode="bypassPermissions",
        max_turns=max(1, cfg.max_turns),
        cwd=str(ROOT),
        env=subscription_env(),
        setting_sources=[],
        effort=cfg.effort or EFFORT,  # type: ignore[arg-type]
    )
    prompt = pack_message(dataset, context_dir)
    cur = Curation(dataset, "", "", 0, 0, None, 0, 0, model_id)
    started = time.time()
    final = ""

    async def _run() -> None:
        nonlocal final
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    texts = [b.text for b in msg.content if isinstance(b, TextBlock)]
                    if texts:
                        final = texts[-1]
                elif isinstance(msg, ResultMessage):
                    cur.n_turns = msg.num_turns
                    cur.cost_usd = msg.total_cost_usd
                    u = msg.usage or {}
                    cur.input_tokens = (
                        int(u.get("input_tokens", 0))
                        + int(u.get("cache_read_input_tokens", 0))
                        + int(u.get("cache_creation_input_tokens", 0))
                    )
                    cur.output_tokens = int(u.get("output_tokens", 0))
                    if msg.result and not final:
                        final = msg.result
                    if msg.is_error:
                        cur.error = f"{msg.subtype}: {(msg.errors or [msg.result or ''])[0]}"[:500]

    try:
        await asyncio.wait_for(_run(), timeout=cfg.timeout_s)
    except TimeoutError:
        cur.error = f"timeout after {cfg.timeout_s}s"
    except Exception as e:  # noqa: BLE001 - recorded, the CLI reports it
        cur.error = f"{type(e).__name__}: {e}"[:500]
    cur.duration_ms = int((time.time() - started) * 1000)
    cur.summary, cur.pitfalls = split_output(final)
    if not cur.summary and not cur.error:
        cur.error = "curator output had no === summary.md === / === pitfalls.md === markers"
    return cur


def write_curation(cur: Curation, context_dir: Path = CONTEXT_DIR) -> None:
    d = context_dir / cur.dataset
    (d / "summary.md").write_text(cur.summary)
    (d / "pitfalls.md").write_text(cur.pitfalls)
    (d / "curation.json").write_text(
        json.dumps(
            {
                "model": cur.model,
                "n_turns": cur.n_turns,
                "duration_ms": cur.duration_ms,
                "cost_usd": cur.cost_usd,
                "input_tokens": cur.input_tokens,
                "output_tokens": cur.output_tokens,
                "error": cur.error,
            },
            indent=1,
        )
        + "\n"
    )


def curate(datasets: list[str], model: str | None = None) -> list[Curation]:
    out: list[Curation] = []
    for ds in datasets:
        cur = asyncio.run(curate_dataset(ds, model=model))
        if not cur.error:
            write_curation(cur)
        out.append(cur)
        try:
            from dab_bench.tracking.mlflow_log import log_curation

            log_curation(cur)
        except Exception:  # noqa: BLE001 - tracking never fails a curation
            pass
    return out
