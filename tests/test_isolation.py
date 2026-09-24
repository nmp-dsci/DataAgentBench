"""An agent session sees its prompt and its dab tools, nothing else (the user's rule).

`check_init` reads the CLI's own init message; these cases are the ways a
session could pick up more: a built-in tool, a connected MCP server, a skill or
plugin, or a working directory the project's memory is keyed to.
"""

import json
from pathlib import Path

import pytest

from dab_bench.agent.isolation import (
    ISOLATION_ENV,
    check_init,
    check_transcript,
    init_record,
    isolated_cwd,
)
from dab_bench.agent.llm import subscription_env
from dab_bench.config import ROOT

TOOLS = ["mcp__dab__query_db", "mcp__dab__return_answer"]


def _init(start: Path, **over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "cwd": str(start),
        "tools": list(TOOLS),
        "mcp_servers": [{"name": "dab", "status": "connected"}],
        "agents": [],
        "skills": [],
        "plugins": [],
        "slash_commands": [],
    }
    return base | over


def test_a_clean_session_passes() -> None:
    cwd = isolated_cwd()
    assert check_init(_init(cwd), TOOLS, cwd) == []


@pytest.mark.parametrize(
    ("over", "needle"),
    [
        ({"tools": [*TOOLS, "Read"]}, "tools beyond"),
        ({"tools": [*TOOLS, "mcp__claude_ai_Gmail__send_message"]}, "tools beyond"),
        ({"mcp_servers": [{"name": "dab"}, {"name": "claude.ai Gmail"}]}, "MCP servers"),
        ({"plugins": [{"name": "nmp-platform"}]}, "plugins"),
        ({"cwd": str(ROOT)}, "cwd"),
    ],
)
def test_anything_extra_is_named(over: dict[str, object], needle: str) -> None:
    cwd = isolated_cwd()
    problems = check_init(_init(cwd, **over), TOOLS, cwd)
    assert len(problems) == 1 and needle in problems[0]


def test_the_session_starts_empty_and_outside_the_repo() -> None:
    cwd = isolated_cwd()
    (cwd / "left_behind.txt").write_text("x")
    cwd = isolated_cwd()
    assert list(cwd.iterdir()) == []
    assert not cwd.resolve().is_relative_to(ROOT.resolve())


def test_the_child_env_switches_memory_and_claude_md_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "0")  # a parent value must not leak
    env = subscription_env()
    for k, v in ISOLATION_ENV.items():
        assert env[k] == v


def test_builtin_skills_and_agents_are_recorded_not_refused() -> None:
    # reachable only through the Skill / Agent tools, which the tools check already refuses
    cwd = isolated_cwd()
    init = _init(cwd, skills=["verify"], agents=["general-purpose"], slash_commands=["compact"])
    assert check_init(init, TOOLS, cwd) == []
    assert init_record(init)["skills_unreachable"] == 1


def test_the_trace_keeps_only_the_listing_fields() -> None:
    rec = init_record({"tools": TOOLS, "apiKeySource": "none", "cwd": "/x", "session_id": "s"})
    assert rec == {"tools": TOOLS, "cwd": "/x"}


def _transcript(tmp: Path, *attachments: dict[str, object]) -> Path:
    p = tmp / "s.jsonl"
    lines = [{"type": "user", "message": {"content": "q"}}]
    lines += [{"type": "attachment", "attachment": a} for a in attachments]
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return p


def test_the_known_cli_context_is_allowed(tmp_path: Path) -> None:
    p = _transcript(
        tmp_path,
        {"type": "environment", "snapshot": {"isGitRepo": False}},
        {"type": "date", "date": "2026-09-23"},
        {"type": "session_context", "context": {"userEmail": "..."}},
    )
    added, problems = check_transcript(p)
    assert problems == [] and added == ["environment", "date", "session_context:userEmail"]


@pytest.mark.parametrize(
    ("attachment", "needle"),
    [
        ({"type": "nested_memory", "content": "MEMORY.md"}, "nested_memory"),
        ({"type": "session_context", "context": {"claudeMd": "# CLAUDE.md"}}, "claudeMd"),
        ({"type": "environment", "snapshot": {"isGitRepo": True}}, "git repo"),
    ],
)
def test_new_context_fails_the_check(
    tmp_path: Path, attachment: dict[str, object], needle: str
) -> None:
    _, problems = check_transcript(_transcript(tmp_path, attachment))
    assert len(problems) == 1 and needle in problems[0]
