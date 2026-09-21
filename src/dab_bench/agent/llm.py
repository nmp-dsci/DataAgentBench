"""The one place a model is named or a billing path chosen (the sibling convention).

Eval runs bill the Claude subscription through the Agent SDK's CLI child;
nothing else in the repo builds a client or reads a key. Ported from
DABStep-loop `agent/llm.py`; the demo-mode branch is dropped because this
explorer has no demo image yet.
"""

from __future__ import annotations

import os
from typing import Literal

from dab_bench.config import settings

MODELS: dict[str, str] = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-5",
    "opus": "claude-opus-5",
}

# Every Agent SDK session in this app (the task agent, the curator) runs at this
# effort unless its agent.yaml pins another. Decided in review: Haiku 4.5, medium.
Effort = Literal["low", "medium", "high", "xhigh", "max"]
EFFORT: Effort = "medium"


class BillingError(RuntimeError):
    """The environment would bill the wrong way, or cannot bill at all."""


def resolve_model(name: str) -> str:
    """`haiku` → `claude-haiku-4-5`; a full model id passes through."""
    return MODELS.get(name.strip().lower(), name)


def short_model(model: str) -> str:
    for alias, full in MODELS.items():
        if full == model:
            return alias
    return model.replace("claude-", "")


def require_live() -> None:
    """Refuse to start a model call in a state where the bill would be a surprise."""
    s = settings()
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if s.billing == "subscription" and key:
        raise BillingError(
            "ANTHROPIC_API_KEY is set while BILLING=subscription. Unset one: with a key present the "
            "CLI bills per token even though the subscription would cover the call."
        )
    if s.billing == "api" and not key:
        raise BillingError("BILLING=api but ANTHROPIC_API_KEY is not set")


def subscription_env() -> dict[str, str]:
    """Environment for the Agent SDK child process, with per-token billing made impossible.

    An `ANTHROPIC_API_KEY` in the child makes the CLI bill per token silently,
    and `CLAUDE_CODE_*` variables make a child started from inside a Claude Code
    session bill against that session. The SDK merges this mapping over the
    parent's environment, so omitting a key is not enough — it has to be blanked.
    """
    drop = {"ANTHROPIC_API_KEY", "CLAUDECODE"}
    env = {
        k: v for k, v in os.environ.items() if k not in drop and not k.startswith("CLAUDE_CODE_")
    }
    if settings().billing == "subscription":
        env["ANTHROPIC_API_KEY"] = ""
        env["CLAUDECODE"] = ""
    return env
