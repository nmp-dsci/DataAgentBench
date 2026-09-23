# CLAUDE.md — DataAgentBench explorer

> Read [`AGENTS.md`](./AGENTS.md) first: what this is, the decisions, the layout,
> the index. [`DESIGN.md`](./DESIGN.md) governs anything visual (explorer, Lavish
> artifacts, README figures). This file is a pointer plus the rules that bite.

## Quick reference

- `make setup` · `make upstream` · `make ingest` · `make rescore` · `make stats`
- `make dev` + `cd frontend && npm run dev` (explorer on :5173, API on :8091)
- agent build: `make platform-up` · `make db-roles` · `make data` · `make context` ·
  `make curate` · `make sandbox` · `make eval SPLIT=smoke|all TRIALS=n`
- `uv run pytest -q` · `make lint` · `make fmt` (`DAB_TEST_PG=1` adds the live role test)

## Rules

- **Only three things call a model**, all through the Agent SDK on the
  subscription: the eval agent (`dab eval`), the curator (`dab context curate`)
  and `llm_extract` inside a trial. `agent/llm.py` is the one place a model is
  named; `require_live()` refuses to start with a per-token key present.
  The explorer, the ingest, the rescore and the context *build* never do —
  the Agent tab's playground runs every tool *except* `llm_extract`, which
  stays display-only (decision D8-A; `DAB_PLAYGROUND_LLM=1` is the only way
  to change that, and it is not wired).
- **The pack is the knowledge base, and it is legitimate by construction.**
  `dab context build` is code; the curator never sees a question;
  `tests/test_context.py` asserts no question text lands in `summary.md` or
  `pitfalls.md`. Never hand-edit the curated files to fit a query — re-curate,
  or change the curator's prompt (`agents/curator/system.md`).
- **The run folder is the record; MLflow is the index.** `runs/<id>/` is what
  the explorer, the profile and a compare read. MLflow (central,
  `dataagentbench/evals`) is linked, never read back. Never start a local
  MLflow; the platform's rule zero applies. The benchmark lives in database
  `dab` on the central Postgres (:5432) since 2026-09-22; `make db-reset` only
  ever drops this project's schema, never the database (platform D16).
- **The questions are not in the data.** `data/index/queries.json` is the
  question set; schema `dataagentbench` holds only what the agent queries, and
  `dab_agent` can read nothing else. `dab data load-questions` keeps a
  convenience copy in `dataagentbench_meta` for ad-hoc SQL — it holds gold, so
  it is granted to nobody but `dab_owner`, and `tests/test_meta.py` asserts the
  agent role is refused. Never put a gold table in `dataagentbench`: that schema
  grants SELECT to `dab_agent` by default.
- **A rate-limited trial is not a fail.** It is `rate_limited`, unscored, and
  `dab eval --resume <run>` finishes it after the window resets.
- **The index is the contract.** The API and the explorer read only
  `data/index/`, `data/answers/`, `data/context/`, `agents/` and `runs/`.
  Never hand-edit those files; change the ingest and re-run it. Never
  hard-code a dataset, a query or a number in the frontend. The one route
  that executes is the playground, `POST /api/agent/tools/<name>`: the
  trial's own tool bodies (`call_tool`), the read-only role, the network-off
  sandbox; it writes no run folder and no MLflow trace, only /work files
  under `workspace/playground/`.
- **Scope is the 54.** `aliases.RELEASED_DATASETS` is the 12 leaderboard
  datasets. The five unreleased datasets upstream are a count in
  `source.json` and nothing more (review decision B). Widening the scope is a
  deliberate change to that set plus a re-ingest and a re-rescore.
- **Re-ingesting is a deliberate bump.** `make upstream` records the commit in
  `source.json`; a PR that changes the index says which upstream commit it
  moved to and what changed.
- **A number carries its denominator.** Pass rates always show `passed/n`;
  a query with no trial reads "not scored", never 0.
- **The rescore is trusted only because it reproduces the site**
  (`tests/test_trials.py`). If a validator upstream changes and the test
  breaks, widen `TOLERATED` with the reason, do not loosen the tolerance.
- **Visuals follow DESIGN.md**: tokens verbatim, assertion headings, one `<em>`
  per page, every number with its baseline. Never the Tailwind/DaisyUI fallback.
- Never add `.lavish/` to `.gitignore`.
- Never commit `data/upstream/`, `runs/`, `workspace/` or any database file.
  `data/context/` (the pack, text only) **is** committed.

## Delegating

Mechanical work (formatting, a scoped test file, a doc pass) can go to a
cheaper model. The ingest, the alias map and the rescore are cross-cutting:
review those changes with a stronger model before merging.
