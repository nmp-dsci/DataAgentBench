"""What an Agent SDK session may see: the prompt it is given and the `dab` tools, nothing else.

The CLI a session runs in would otherwise pick things up from where it starts:
CLAUDE.md files, the auto-memory kept per working directory, settings, skills,
plugins and connected MCP servers. `session_options` already passes no settings
sources, no built-in tools and a strict MCP config; this module closes the rest
and checks the result:

- the session starts in an empty directory outside the repo, so no project
  file and no project memory is keyed to it;
- the environment switches the CLI's auto-memory and CLAUDE.md loading off;
- the CLI's `init` message (the tools, MCP servers, skills, plugins and
  agents the session actually has) is recorded on the trace, and any tool,
  server or plugin beyond the version's own `dab` tools stops the run;
- `dab isolation-check` also reads the session's transcript and allows only
  the context the CLI is known to add (below), so a new kind of injection
  fails the check instead of reaching the model unnoticed.

The CLI's built-in skills, sub-agents and slash commands appear in `init` but
are unreachable: a model can only use them through the Skill or Agent tool,
and a session has neither, so they are recorded, not refused. One thing the
CLI adds cannot be switched off: the logged-in account's email, as session
context. It never reaches a run's trace or MLflow, which record only the
prompt and messages this code passes and receives.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from dab_bench.config import ROOT

# Read by the CLI: no auto-memory directory, no CLAUDE.md from any level.
ISOLATION_ENV: dict[str, str] = {
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
}

# Passed as the session's only settings: the CLI's one built-in plugin that loads instruction
# files (AGENTS.md, where CLAUDE.md would be) is switched off, not merely left with nothing to find.
SESSION_SETTINGS = '{"enabledPlugins": {"agents-md@builtin": false}}'

# Plugins can bring tools and hooks with them, so none may load.
_MUST_BE_EMPTY = ("plugins",)
# Listed by the CLI but reachable only through the Skill / Agent tools, which a session lacks.
_UNREACHABLE = ("agents", "skills", "slash_commands")

# What the CLI may add to the model's context beyond the system prompt and the question,
# as seen in a session transcript (2.1.277): the attachment type, and for session context
# the keys it may carry. Anything else (a CLAUDE.md, memory, a skill listing, git status)
# fails `dab isolation-check`.
ALLOWED_ATTACHMENTS = {
    "environment",  # working directory (the empty one), platform, shell, OS
    "model",  # the model's name
    "total_tokens_reminder",
    "date",
    "prompt_snapshot",  # the system prompt this code passed
    "session_context",
}
ALLOWED_SESSION_CONTEXT = {"userEmail"}


class IsolationError(RuntimeError):
    """The session was given something beyond its prompt and its `dab` tools."""


def isolated_cwd() -> Path:
    """An empty directory outside the repo for the session to start in."""
    d = Path(tempfile.gettempdir()) / "dab-agent-cwd"
    if d.resolve().is_relative_to(ROOT.resolve()):
        raise IsolationError(f"{d} is inside the repo")
    d.mkdir(parents=True, exist_ok=True)
    # sessions have no file tools, so nothing should ever land here; if something did,
    # clear it rather than let the next session start next to it
    for child in d.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    return d


def init_record(data: dict[str, Any]) -> dict[str, Any]:
    """The part of the CLI's init message worth keeping on the trace (counts for the
    unreachable listings, which are long and the same every time)."""
    keep = ("cwd", "model", "permissionMode", "tools", "mcp_servers", *_MUST_BE_EMPTY)
    rec = {k: data.get(k) for k in keep if k in data}
    rec |= {f"{k}_unreachable": len(data.get(k) or []) for k in _UNREACHABLE if k in data}
    return rec


def check_init(data: dict[str, Any], allowed_tools: list[str], cwd: Path) -> list[str]:
    """Every way `data` (the CLI's init message) exceeds what the session was given."""
    problems: list[str] = []
    tools = [str(t) for t in data.get("tools") or []]
    extra = sorted(set(tools) - set(allowed_tools))
    if extra:
        problems.append(f"tools beyond the version's own: {extra}")
    servers = sorted(
        str(s.get("name") if isinstance(s, dict) else s) for s in data.get("mcp_servers") or []
    )
    if servers not in ([], ["dab"]):
        problems.append(f"MCP servers beyond dab: {servers}")
    for k in _MUST_BE_EMPTY:
        v = data.get(k)
        if v:
            problems.append(f"{k}: {v}")
    got = data.get("cwd")
    if got and Path(str(got)).resolve() != cwd.resolve():
        problems.append(f"cwd {got}, expected {cwd}")
    return problems


def check_transcript(path: Path) -> tuple[list[str], list[str]]:
    """The context the CLI added in a session transcript: (what it added, problems).

    Reads the JSONL the CLI writes per session. Every `attachment` entry is something
    the model received besides the system prompt and the user's message."""
    added: list[str] = []
    problems: list[str] = []
    for line in path.read_text().splitlines():
        e = json.loads(line) if line.strip() else {}
        if e.get("type") != "attachment":
            continue
        a = e.get("attachment") or {}
        kind = str(a.get("type"))
        if kind == "session_context":
            keys = sorted((a.get("context") or {}).keys())
            added.append(f"session_context:{','.join(keys)}")
            extra = sorted(set(keys) - ALLOWED_SESSION_CONTEXT)
            if extra:
                problems.append(f"session context beyond the allowed: {extra}")
            continue
        added.append(kind)
        if kind not in ALLOWED_ATTACHMENTS:
            problems.append(f"context the CLI added: {kind}")
        if kind == "environment" and (a.get("snapshot") or {}).get("isGitRepo"):
            problems.append("the session started inside a git repo")
    return added, problems
