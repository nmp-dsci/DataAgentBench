"""The tool table: one body per tool, reached the same way by a trial (the MCP server) and the playground.

Only the pack-backed tools run here (no Postgres, no sandbox, no model). `DAB_TEST_PG=1`
adds a live `query_db` round trip on the read-only role.
"""

from __future__ import annotations

import os
from typing import Any

import mcp.types as mcp_types
import pytest

from dab_bench.agent.prompt import load_context
from dab_bench.agent.tools import TOOL_SPECS, ToolState, call_tool, make_tool_server


def _state(dataset: str = "yelp") -> ToolState:
    return ToolState(dataset=dataset, ctx=load_context(dataset), trial_key="test", sandbox=None)


def test_every_spec_has_a_body_or_is_the_model_tool() -> None:
    from dab_bench.agent.tools import _BODIES

    assert set(TOOL_SPECS) == set(_BODIES) | {"llm_extract"}
    assert TOOL_SPECS["llm_extract"].calls_model and not TOOL_SPECS["query_db"].calls_model
    assert TOOL_SPECS["query_db"].schema["required"] == ["sql"]  # optional params stay optional


def test_call_tool_records_the_call_like_a_trial() -> None:
    st = _state()
    out, err = call_tool(st, "search_context", {"term": "business_id"})
    assert not err and "business_id" in out
    out, err = call_tool(st, "read_context", {"path": "../../../etc/passwd"})
    assert err and out.startswith(
        "Error: path must be inside"
    )  # every "Error:" output is flagged now
    out, err = call_tool(st, "execute_python", {"code": "print(1)"})
    assert err and "no sandbox" in out
    out, err = call_tool(st, "return_answer", {"answer": "  42 "})
    assert st.answer == "42" and not err
    assert [c["tool"] for c in st.calls] == [
        "search_context",
        "read_context",
        "execute_python",
        "return_answer",
    ]
    with pytest.raises(KeyError):
        call_tool(st, "nope", {})


async def _mcp_call(server: Any, name: str, args: dict[str, Any]) -> mcp_types.CallToolResult:
    h = server._request_handlers["tools/call"].handler
    return await h(None, mcp_types.CallToolRequestParams(name=name, arguments=args))  # type: ignore[no-any-return]


@pytest.mark.anyio
async def test_mcp_server_and_call_tool_give_the_same_output() -> None:
    a, b = _state(), _state()
    server = make_tool_server(a)["instance"]
    listed = await server._request_handlers["tools/list"].handler(None, None)
    assert [t.name for t in listed.tools] == list(TOOL_SPECS)
    for name, args in (
        ("list_db", {}),
        ("read_context", {"path": "summary.md"}),
        ("search_context", {"term": "review"}),
        ("execute_python", {"code": "print(1)"}),
    ):
        r = await _mcp_call(server, name, args)
        out, err = call_tool(b, name, args)
        assert r.content[0].text == out, name  # type: ignore[union-attr]
        assert bool(r.is_error) == err, name
    assert [c["tool"] for c in a.calls] == [c["tool"] for c in b.calls]


@pytest.mark.skipif(
    not os.environ.get("DAB_TEST_PG"), reason="needs the local Postgres (DAB_TEST_PG=1)"
)
def test_query_db_on_the_read_only_role() -> None:
    st = _state()
    out, err = call_tool(st, "query_db", {"sql": "select count(*) as n from yelp_business"})
    assert not err and out.startswith("n\n")
    out, err = call_tool(st, "query_db", {"sql": "delete from yelp_business"})
    assert err and "Error" in out


def test_agent_api_lists_versions_and_guards_the_playground() -> None:
    from fastapi.testclient import TestClient

    from dab_bench.serving import app as serving

    client = TestClient(serving.create_app())
    board = client.get("/api/agents").json()
    assert board["champion"] == "v0" and [v["name"] for v in board["versions"]] == ["v0"]
    detail = client.get("/api/agents/champion").json()
    assert detail["name"] == "v0" and detail["champion"] is True
    modes = {t["name"]: t["playground"] for t in detail["tools"]}
    assert modes["llm_extract"] == "off" and modes["return_answer"] == "echo"
    assert modes["query_db"] == "on" and len(modes) == 9
    prompt = client.get("/api/agents/v0/prompt", params={"dataset": "yelp"}).json()
    assert prompt["chars"] > 5000 and prompt["prompt"].startswith(detail["files"]["system.md"][:40])
    assert client.get("/api/agents/nope").status_code == 404
    assert client.get("/api/agents/v0/prompt", params={"dataset": "nope"}).status_code == 404
    assert client.post("/api/agent/tools/nope", json={"dataset": "yelp"}).status_code == 400
    assert (
        client.post("/api/agent/tools/query_db", json={"dataset": "yelp", "input": {}}).status_code
        == 400
    )
    llm = client.post(
        "/api/agent/tools/llm_extract",
        json={"dataset": "yelp", "input": {"sql": "s", "column": "c", "instruction": "i"}},
    )
    assert llm.status_code == 403
    r = client.post(
        "/api/agent/tools/search_context", json={"dataset": "yelp", "input": {"term": "stars"}}
    ).json()
    assert r["error"] is False and "stars" in r["output"] and r["elapsed_s"] >= 0
    echo = client.post(
        "/api/agent/tools/return_answer", json={"dataset": "yelp", "input": {"answer": "42"}}
    ).json()
    assert echo["output"].startswith("recorded")
