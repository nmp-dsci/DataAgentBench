"""F1b: a refused write_notes call must not persist the raw leaking text (agent/optimise.py).

Before the fix, `sess.refusals` stored the raw `notes`/`rationale` strings verbatim for
every refusal, including ones the guard just flagged as a leak — so a refused-but-not-yet-
dropped (or even dropped) call could land question text, a gold value or golden SQL
verbatim in optimise.json / runs/<run>/optimise/<into>/*.json. This exercises the real
`write_notes` MCP tool body through the same call path a trial uses (`tests/test_tools.py`'s
`_mcp_call` pattern) and asserts the leaking text is gone from the stored record.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import mcp.types as mcp_types
import pytest

from dab_bench.agent.optimise import Session, _server
from dab_bench.agent.prompt import load_context
from dab_bench.agent.tools import ToolState
from dab_bench.eval.guards import Guard

QUESTION = "How many repositories have more than a hundred open issues right now"
LEAK_NOTES = f"Remember that {QUESTION} needs a careful join on the issues table."


async def _mcp_call(server: Any, name: str, args: dict[str, Any]) -> mcp_types.CallToolResult:
    h = server._request_handlers["tools/call"].handler
    return await h(None, mcp_types.CallToolRequestParams(name=name, arguments=args))


def _guard() -> Guard:
    return Guard(questions=[QUESTION], golds=[], golden_sqls=[], max_chars=1_500)


@pytest.mark.anyio
async def test_a_refused_leak_is_stored_without_the_raw_text() -> None:
    sess = Session(scope="deps_dev_v1")
    guard = _guard()
    state = ToolState(
        dataset="deps_dev_v1", ctx=load_context("deps_dev_v1"), trial_key="t", sandbox=None
    )
    server = _server(state, sess, guard, "deps_dev_v1")["instance"]

    r = await _mcp_call(
        server, "write_notes", {"notes": LEAK_NOTES, "rationale": "seen in the data"}
    )
    assert r.is_error

    assert len(sess.refusals) == 1
    entry = sess.refusals[0]
    assert "notes" not in entry and "rationale" not in entry
    assert entry["redacted"] is True
    assert entry["notes_chars"] == len(LEAK_NOTES)
    assert entry["problems"]

    blob = str(asdict(sess))
    assert QUESTION not in blob
    assert LEAK_NOTES not in blob


@pytest.mark.anyio
async def test_a_dropped_session_redacts_the_stored_rationale_too() -> None:
    sess = Session(scope="deps_dev_v1")
    guard = _guard()
    state = ToolState(
        dataset="deps_dev_v1", ctx=load_context("deps_dev_v1"), trial_key="t", sandbox=None
    )
    server = _server(state, sess, guard, "deps_dev_v1")["instance"]

    # two leak refusals in a row drop the session (agent/optimise.py's documented rule)
    await _mcp_call(server, "write_notes", {"notes": LEAK_NOTES, "rationale": "ok"})
    r2 = await _mcp_call(server, "write_notes", {"notes": LEAK_NOTES, "rationale": LEAK_NOTES})
    assert r2.is_error
    assert sess.dropped is True
    assert sess.notes is None
    assert sess.rationale == "[redacted]"

    for entry in sess.refusals:
        assert "notes" not in entry and "rationale" not in entry
    blob = str(asdict(sess))
    assert QUESTION not in blob


@pytest.mark.anyio
async def test_a_long_rationale_is_not_a_refusal_but_a_leaking_one_is() -> None:
    sess = Session(scope="playbook:keys", kind="component")
    guard = Guard(questions=[QUESTION], golds=[], golden_sqls=[], max_chars=100)
    state = ToolState(dataset="", ctx=load_context("yelp"), trial_key="t", sandbox=None)
    server = _server(state, sess, guard, None, "write_section", True)["instance"]
    r = await _mcp_call(
        server, "write_section", {"notes": "- strip the prefix", "rationale": "x " * 200}
    )
    assert not r.is_error and sess.notes == "- strip the prefix"  # a 400-char rationale is fine
    assert sess.attempts == [{"ok": True, "chars": 18, "problems": []}]
    sess2 = Session(scope="playbook:keys", kind="component")
    server = _server(state, sess2, guard, None, "write_section", True)["instance"]
    r = await _mcp_call(server, "write_section", {"notes": "- ok", "rationale": LEAK_NOTES})
    assert r.is_error and sess2.notes is None and sess2.attempts[0]["ok"] is False
