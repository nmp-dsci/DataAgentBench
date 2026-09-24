"""One (query, trial), one Agent SDK session, one trace.

The system prompt is `system.md` plus the dataset's facts (D7 A); the user
message is the question. The `dab` MCP server, holding only the version's own
tools, is the whole toolbox. The answer is what `submit_answer` or
`return_answer` recorded, else the last plain text (the reference scaffold's
rule). A version that answers with SQL also leaves its submission on the trace:
the SQL, the harness's re-run of it, the mode and the step. Everything the model
saw and did is the trace the run keeps and MLflow indexes.
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
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from dab_bench.agent.isolation import (
    SESSION_SETTINGS,
    IsolationError,
    check_init,
    check_transcript,
    init_record,
    isolated_cwd,
)
from dab_bench.agent.llm import EFFORT, require_live, resolve_model, subscription_env
from dab_bench.agent.prompt import DatasetContext, user_message
from dab_bench.agent.sandbox import Sandbox
from dab_bench.agent.tools import ToolState, make_tool_server
from dab_bench.agent.versions import AgentVersion
from dab_bench.data.aliases import trace_stem
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
    rate_limited: bool = False
    session_id: str | None = None
    model: str = ""
    effort: str = EFFORT
    context_sha: str = ""
    system_prompt_chars: int = 0
    submission: dict[str, Any] | None = (
        None  # submit_answer: sql, mode, step, columns, rows, result
    )

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


_RATE_LIMIT = ("hit your session limit", "hit your limit", "rate_limit", "usage limit")


def usage_dict(u: dict[str, Any] | None) -> dict[str, int] | None:
    """The four counts a message bills, from the API's usage block."""
    if not u:
        return None
    return {
        "input": int(u.get("input_tokens", 0) or 0),
        "cache_read": int(u.get("cache_read_input_tokens", 0) or 0),
        "cache_creation": int(u.get("cache_creation_input_tokens", 0) or 0),
        "output": int(u.get("output_tokens", 0) or 0),
    }


def _rate_limited(text: str, error: str | None, reason: str | None) -> bool:
    blob = f"{text}\n{error or ''}".lower()
    return reason == "api_error" and any(m in blob for m in _RATE_LIMIT) or "rate_limit" in blob


def trial_key(query: Query, trial: int) -> str:
    return trace_stem(f"{query.dataset}/{query.query_id}", trial)


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
    system_prompt = version.prompt_for(ctx, use_hints)
    key = trial_key(query, trial)
    state = ToolState(
        dataset=query.dataset,
        ctx=ctx,
        trial_key=key,
        sandbox=sandbox,
        exec_timeout_s=cfg.exec_timeout_s,
    )
    server = make_tool_server(state, list(cfg.tools))
    cwd = isolated_cwd()
    options = session_options(version, system_prompt, server, cwd, model_id, eff)
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
                if isinstance(msg, SystemMessage) and msg.subtype == "init":
                    # what the CLI actually gave the session; anything beyond the version's
                    # own dab tools stops the run, since every trial after it would share it
                    s.trace.append({"role": "init", "content": init_record(msg.data)})
                    problems = check_init(msg.data, list(cfg.tools), cwd)
                    if problems:
                        raise IsolationError("; ".join(problems))
                elif isinstance(msg, AssistantMessage):
                    blocks = [_block_to_dict(b) for b in msg.content]
                    s.trace.append(
                        {
                            "role": "assistant",
                            "content": blocks,
                            "t": round(time.time() - started, 3),
                            # one API message arrives as several entries (one per block) that
                            # repeat the same usage; message_id lets a reader bill it once
                            "message_id": msg.message_id,
                            "usage": usage_dict(msg.usage),
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
    except IsolationError:
        raise
    except TimeoutError:
        s.error = f"timeout after {cfg.timeout_s}s"
        s.terminal_reason = "timeout"
        s.timed_out = True
    except Exception as e:  # noqa: BLE001 - recorded on the row, the run continues
        s.error = f"{type(e).__name__}: {e}"[:500]
    finally:
        if sandbox is not None:
            sandbox.release(key)
    s.duration_ms = int((time.time() - started) * 1000)
    if _rate_limited(final_text, s.error, s.terminal_reason):
        # the subscription window closed mid-trial: not an answer, not a fail — a retry
        s.error = "rate_limited: " + (final_text or s.error or "")[:120]
        s.terminal_reason = "rate_limited"
        s.rate_limited = True
        final_text = ""
    s.final_text = final_text
    s.answer = state.answer if state.answer is not None else final_text.strip()
    s.submission = state.submission
    s.tool_calls = state.calls
    if state.extract_cost_usd:
        s.cost_usd = (s.cost_usd or 0.0) + state.extract_cost_usd
        s.input_tokens += state.extract_input_tokens
        s.output_tokens += state.extract_output_tokens
    return s


def session_options(
    version: AgentVersion,
    system_prompt: str,
    server: Any,
    cwd: Path,
    model_id: str,
    effort: str,
    max_turns: int | None = None,
) -> ClaudeAgentOptions:
    """The one place an eval session's options are built, so `isolation_check` sees exactly
    what a trial sees."""
    cfg = version.config
    return ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=model_id,
        tools=[],  # no built-in tools: the dab server is the whole toolbox
        allowed_tools=list(cfg.tools),
        mcp_servers={"dab": server},
        strict_mcp_config=True,
        permission_mode="bypassPermissions",
        max_turns=max_turns or cfg.max_turns,
        cwd=str(cwd),  # empty and outside the repo: no project file or memory is keyed to it
        env=subscription_env(),
        setting_sources=[],
        settings=SESSION_SETTINGS,
        effort=effort,  # type: ignore[arg-type]
    )


async def isolation_check(version: AgentVersion, ctx: DatasetContext) -> dict[str, Any]:
    """Start one session exactly as a trial would and report what the CLI gave it.

    One short turn on the subscription (the eval agent's own path): the prompt asks for a
    one-word reply and no tool call. Returns the init record and every problem found."""
    require_live()
    cfg = version.config
    state = ToolState(dataset=ctx.dataset, ctx=ctx, trial_key="isolation_check", sandbox=None)
    cwd = isolated_cwd()
    system_prompt = version.prompt_for(ctx)
    options = session_options(
        version,
        system_prompt,
        make_tool_server(state, list(cfg.tools)),
        cwd,
        resolve_model(cfg.model),
        cfg.effort or EFFORT,
        max_turns=1,
    )
    out: dict[str, Any] = {"init": None, "context_added": [], "problems": [], "reply": ""}
    session_id = None
    async with ClaudeSDKClient(options=options) as client:
        await client.query("Reply with the single word OK. Do not call any tool.")
        async for msg in client.receive_response():
            if isinstance(msg, SystemMessage) and msg.subtype == "init":
                out["init"] = init_record(msg.data)
                out["problems"] += check_init(msg.data, list(cfg.tools), cwd)
            elif isinstance(msg, AssistantMessage):
                texts = [b.text for b in msg.content if isinstance(b, TextBlock)]
                if texts:
                    out["reply"] = texts[-1]
            elif isinstance(msg, ResultMessage):
                session_id = msg.session_id
    if out["init"] is None:
        out["problems"].append("no init message")
    projects = Path.home() / ".claude" / "projects"
    transcript = next(projects.glob(f"*/{session_id}.jsonl"), None) if session_id else None
    if transcript is None:
        out["problems"].append("no session transcript to read")
    else:
        out["context_added"], problems = check_transcript(transcript)
        out["problems"] += problems
    return out


def save_trace(path: Path, s: Solve) -> None:
    path.write_text(json.dumps(s.as_dict(), ensure_ascii=False, indent=1), encoding="utf-8")


def backfill_usage(run_dir: Path) -> tuple[int, int]:
    """Write `message_id` and `usage` onto the assistant entries of every trace under
    `run_dir/traces/` from the SDK session transcript, matching assistant lines in order.
    Returns (updated, skipped); a trace already carrying usage counts as skipped."""
    # the CLI keeps a session's transcript under a folder named for the directory it started
    # in: the repo root for runs before the isolated cwd, the isolated cwd since
    projects = Path.home() / ".claude" / "projects"
    updated = skipped = 0
    for tp in sorted((run_dir / "traces").glob("*.json")):
        t = json.loads(tp.read_text())
        entries = [e for e in t.get("trace") or [] if e.get("role") == "assistant"]
        sid = t.get("session_id")
        src = next(projects.glob(f"*/{sid}.jsonl"), None) if sid else None
        if not entries or entries[0].get("usage") or src is None or not src.exists():
            skipped += 1
            continue
        lines = []
        for line in src.read_text().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            if d.get("type") == "assistant":
                lines.append(d.get("message") or {})
        # a timed-out trial's trace is a prefix of the transcript (the child kept going);
        # line up on block types so a mismatch is caught, not guessed
        lines = lines[: len(entries)]
        same_shape = len(lines) == len(entries) and all(
            [b.get("type") for b in (e.get("content") or [])]
            == [b.get("type") for b in (m.get("content") or [])]
            for e, m in zip(entries, lines, strict=True)
        )
        if not same_shape:
            skipped += 1
            continue
        for e, m in zip(entries, lines, strict=True):
            e["message_id"] = m.get("id")
            e["usage"] = usage_dict(m.get("usage"))
        tp.write_text(json.dumps(t, ensure_ascii=False))
        updated += 1
    return updated, skipped
