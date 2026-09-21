"""One (query, trial), one Agent SDK session, one trace.

The system prompt is `system.md` plus the dataset's curated facts (D7 A); the
user message is the question. The `dab` MCP server is the whole toolbox. The
answer is what `return_answer` recorded, else the last plain text (the
reference scaffold's rule). Everything the model saw and did is the trace the
run keeps and MLflow indexes.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from dab_bench.agent.llm import EFFORT, require_live, resolve_model, subscription_env
from dab_bench.agent.prompt import DatasetContext, compose_system_prompt, user_message
from dab_bench.agent.sandbox import Sandbox
from dab_bench.agent.tools import ToolState, make_tool_server
from dab_bench.agent.versions import AgentVersion
from dab_bench.config import ROOT
from dab_bench.eval.splits import Query


@dataclass
class Solve:
    query_id: str
    dataset: str
    trial: int
    answer: str
    final_text: str
    trace: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    n_turns: int = 0
    duration_ms: int = 0
    cost_usd: float | None = None
    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    terminal_reason: str | None = None
    timed_out: bool = False
    session_id: str | None = None
    model: str = ""
    effort: str = EFFORT
    context_sha: str = ""
    system_prompt_chars: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _block_to_dict(b: Any) -> dict[str, Any]:
    if isinstance(b, TextBlock):
        return {"type": "text", "text": b.text}
    if isinstance(b, ThinkingBlock):
        return {"type": "thinking", "thinking": b.thinking}
    if isinstance(b, ToolUseBlock):
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    if isinstance(b, ToolResultBlock):
        content = b.content
        if isinstance(content, list):
            content = "\n".join(str(c.get("text", "")) for c in content if isinstance(c, dict))
        return {
            "type": "tool_result",
            "tool_use_id": b.tool_use_id,
            "content": content,
            "is_error": b.is_error,
        }
    return {"type": type(b).__name__, "repr": repr(b)[:2000]}


def trial_key(query: Query, trial: int) -> str:
    return f"{query.dataset}_{query.query_id}_t{trial}"


async def solve(
    version: AgentVersion,
    query: Query,
    ctx: DatasetContext,
    trial: int,
    sandbox: Sandbox | None,
    model: str | None = None,
    effort: str | None = None,
    hints: bool | None = None,
) -> Solve:
    require_live()
    cfg = version.config
    model_id = resolve_model(model or cfg.model)
    eff = effort or cfg.effort or EFFORT
    use_hints = cfg.hints if hints is None else hints
    system_prompt = compose_system_prompt(version.system_prompt, ctx, hints=use_hints)
    key = trial_key(query, trial)
    state = ToolState(
        dataset=query.dataset,
        ctx=ctx,
        trial_key=key,
        sandbox=sandbox,
        exec_timeout_s=cfg.exec_timeout_s,
    )
    server = make_tool_server(state)
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=model_id,
        tools=[],  # no built-in tools: the dab server is the whole toolbox
        allowed_tools=list(cfg.tools),
        mcp_servers={"dab": server},
        strict_mcp_config=True,
        permission_mode="bypassPermissions",
        max_turns=cfg.max_turns,
        cwd=str(ROOT),
        env=subscription_env(),
        setting_sources=[],
        effort=eff,  # type: ignore[arg-type]
    )
    prompt = user_message(query.question)
    s = Solve(
        query_id=query.id,
        dataset=query.dataset,
        trial=trial,
        answer="",
        final_text="",
        model=model_id,
        effort=eff,
        context_sha=ctx.context_sha,
        system_prompt_chars=len(system_prompt),
    )
    s.trace.append({"role": "system", "content": system_prompt})
    s.trace.append({"role": "user", "content": prompt})
    started = time.time()
    final_text = ""

    async def _run() -> None:
        nonlocal final_text
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    blocks = [_block_to_dict(b) for b in msg.content]
                    s.trace.append(
                        {
                            "role": "assistant",
                            "content": blocks,
                            "t": round(time.time() - started, 3),
                        }
                    )
                    texts = [b["text"] for b in blocks if b["type"] == "text" and b["text"].strip()]
                    if texts:
                        final_text = texts[-1]
                elif isinstance(msg, UserMessage) and not isinstance(msg.content, str):
                    blocks = [_block_to_dict(b) for b in msg.content]
                    s.trace.append(
                        {"role": "tool", "content": blocks, "t": round(time.time() - started, 3)}
                    )
                elif isinstance(msg, ResultMessage):
                    s.n_turns = msg.num_turns
                    s.cost_usd = msg.total_cost_usd
                    s.session_id = msg.session_id
                    s.terminal_reason = msg.terminal_reason or msg.subtype
                    u = msg.usage or {}
                    s.input_tokens = int(u.get("input_tokens", 0))
                    s.cache_read_tokens = int(u.get("cache_read_input_tokens", 0))
                    s.cache_creation_tokens = int(u.get("cache_creation_input_tokens", 0))
                    s.output_tokens = int(u.get("output_tokens", 0))
                    if msg.result and not final_text:
                        final_text = msg.result
                    if msg.is_error:
                        s.error = f"{msg.subtype}: {(msg.errors or [msg.result or ''])[0]}"[:500]

    try:
        await asyncio.wait_for(_run(), timeout=cfg.timeout_s)
    except TimeoutError:
        s.error = f"timeout after {cfg.timeout_s}s"
        s.terminal_reason = "timeout"
        s.timed_out = True
    except Exception as e:  # noqa: BLE001 - recorded on the row, the run continues
        s.error = f"{type(e).__name__}: {e}"[:500]
    s.duration_ms = int((time.time() - started) * 1000)
    s.final_text = final_text
    s.answer = state.answer if state.answer is not None else final_text.strip()
    s.tool_calls = state.calls
    if state.extract_cost_usd:
        s.cost_usd = (s.cost_usd or 0.0) + state.extract_cost_usd
        s.input_tokens += state.extract_input_tokens
        s.output_tokens += state.extract_output_tokens
    return s


def save_trace(path: Path, s: Solve) -> None:
    path.write_text(json.dumps(s.as_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
