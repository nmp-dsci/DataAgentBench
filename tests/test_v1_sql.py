"""The SQL-answer challenger (plan s06, D26–D28): its prompt, its three tools and the submit contract.

No model and no Postgres: `submit_answer`'s re-run goes through the golden's own executor,
which these tests replace with a fixed result, so the contract is checked, not the data.
"""

from __future__ import annotations

from typing import Any

import pytest

from dab_bench.agent.isolation import check_init, isolated_cwd
from dab_bench.agent.prompt import compose_system_prompt, load_context
from dab_bench.agent.tools import ToolState, call_tool, make_tool_server, specs_for
from dab_bench.agent.versions import load_version
from dab_bench.eval import golden
from dab_bench.eval.golden import Execution


def _state(dataset: str = "deps_dev_v1") -> ToolState:
    return ToolState(dataset=dataset, ctx=load_context(dataset), trial_key="test", sandbox=None)


@pytest.mark.parametrize("dataset", ["deps_dev_v1", "github_repos", "yelp"])
def test_the_prompt_holds_both_upstream_files_verbatim_and_no_pack(dataset: str) -> None:
    v = load_version("v1_sql")
    ctx = load_context(dataset)
    prompt = v.prompt_for(ctx)
    # verbatim: only trailing whitespace at the very end of a file is trimmed
    assert ctx.description.rstrip() in prompt and ctx.hints.rstrip() in prompt
    assert not ctx.description[:1].isspace() and not ctx.hints[:1].isspace()
    assert "## Summary (curated" not in prompt and "## Pitfalls in the data" not in prompt
    assert prompt.startswith(v.system_prompt.rstrip())
    order = ["## Tables", "## Database description", "## Hints"]
    assert [prompt.index(h) for h in order] == sorted(prompt.index(h) for h in order)


def test_notes_sit_between_the_tables_map_and_the_description() -> None:
    ctx = load_context("deps_dev_v1")
    prompt = compose_system_prompt("S", ctx, hints=True, pack=False, notes="strip commas")
    assert prompt.index("## Tables") < prompt.index("## Notes for this dataset")
    assert prompt.index("strip commas") < prompt.index("## Database description")
    # v0 keeps its prompt: pack on, no notes block
    v0 = load_version("v0").prompt_for(ctx)
    assert "## Pitfalls in the data" in v0 and "## Notes for this dataset" not in v0


def test_v1_sql_has_three_tools_and_query_db_lost_save_as() -> None:
    v = load_version("v1_sql")
    specs = specs_for(list(v.config.tools))
    assert [s.name for s in specs] == ["describe_table", "query_db", "submit_answer"]
    assert "save_as" not in specs[1].schema["properties"]
    assert not v.needs_sandbox and v.submits_sql
    assert load_version("v0").needs_sandbox and not load_version("v0").submits_sql


@pytest.mark.anyio
async def test_the_server_registers_only_the_versions_tools() -> None:
    v = load_version("v1_sql")
    server = make_tool_server(_state(), list(v.config.tools))["instance"]
    listed = await server._request_handlers["tools/list"].handler(None, None)
    assert sorted(t.name for t in listed.tools) == [
        "describe_table",
        "query_db",
        "submit_answer",
    ]


def test_the_isolation_check_refuses_a_tool_beyond_the_three() -> None:
    cwd = isolated_cwd()
    tools = list(load_version("v1_sql").config.tools)
    init: dict[str, Any] = {
        "cwd": str(cwd),
        "tools": tools,
        "mcp_servers": [{"name": "dab"}],
        "plugins": [],
    }
    assert check_init(init, tools, cwd) == []
    extra = init | {"tools": [*tools, "mcp__dab__execute_python"]}
    assert "tools beyond the version's own" in check_init(extra, tools, cwd)[0]


@pytest.fixture
def fixed_result(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def fake(sql: str) -> Execution:
        seen.append(sql)
        if "boom" in sql:
            return Execution([], [], 0, False, 1, 'Error: column "boom" does not exist')
        if "empty" in sql:
            return Execution(["n"], [], 0, False, 1)
        return Execution(["name", "stars"], [["a/b", 10.0], ["c/d", 7]], 2, False, 3)

    monkeypatch.setattr(golden, "execute", fake)
    return seen


def test_pass_through_answer_is_the_render_of_the_rerun(fixed_result: list[str]) -> None:
    st = _state()
    out, err = call_tool(
        st, "submit_answer", {"sql": "select x ;", "mode": "pass_through", "answer": "ignored"}
    )
    assert not err and fixed_result == ["select x ;"]
    expected = golden.render(["name", "stars"], [["a/b", 10.0], ["c/d", 7]])
    assert st.answer == expected == "name,stars\na/b,10\nc/d,7"
    sub = st.submission or {}
    assert sub["mode"] == "pass_through" and sub["result"] == expected
    assert sub["columns"] == ["name", "stars"] and sub["row_count"] == 2
    assert sub["model_answer"] == "ignored"  # kept, but never the scored answer
    assert "Do not call any more tools" in out


def test_derived_answer_is_the_models_and_keeps_the_step(fixed_result: list[str]) -> None:
    st = _state()
    args = {"sql": "select x", "mode": "derived", "answer": "a/b", "step": "took the top row"}
    out, err = call_tool(st, "submit_answer", args)
    assert not err and st.answer == "a/b"
    assert (st.submission or {})["step"] == "took the top row"
    assert (st.submission or {})["result"] == "name,stars\na/b,10\nc/d,7"


@pytest.mark.parametrize(
    ("args", "says"),
    [
        ({"sql": "select boom", "mode": "pass_through"}, "failed when re-run"),
        ({"sql": "select empty", "mode": "pass_through"}, "no rows"),
        ({"sql": "select x", "mode": "derived"}, "needs `answer`"),
        ({"sql": "select x", "mode": "guess"}, "mode must be one of"),
    ],
)
def test_a_bad_submission_is_sent_back_and_nothing_recorded(
    fixed_result: list[str], args: dict[str, str], says: str
) -> None:
    st = _state()
    out, err = call_tool(st, "submit_answer", args)
    assert err and says in out and "nothing recorded" in out
    assert st.answer is None and st.submission is None


def test_the_last_good_submission_wins(fixed_result: list[str]) -> None:
    st = _state()
    call_tool(st, "submit_answer", {"sql": "select x", "mode": "derived", "answer": "a/b"})
    call_tool(st, "submit_answer", {"sql": "select boom", "mode": "pass_through"})
    assert st.answer == "a/b"  # a failed resubmission does not erase the recorded one
