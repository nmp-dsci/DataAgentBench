# CLAUDE.md — DataAgentBench explorer

> Read [`AGENTS.md`](./AGENTS.md) first: what this is, the decisions, the layout,
> the index. [`DESIGN.md`](./DESIGN.md) governs anything visual (explorer, Lavish
> artifacts, README figures). This file is a pointer plus the rules that bite.

## Quick reference

- `make setup` · `make upstream` · `make ingest` · `make rescore` · `make stats`
- `make dev` + `cd frontend && npm run dev` (explorer on :5173, API on :8091)
- `uv run pytest -q` · `make lint` · `make fmt`

## Rules

- **This build calls no model.** There is no model dependency in
  `pyproject.toml` and no key in `.env.example`. Do not add one here; the agent
  is a later build with its own plan.
- **The index is the contract.** The API and the explorer read only
  `data/index/` and `data/answers/`. Never hand-edit those files; change the
  ingest and re-run it. Never hard-code a dataset, a query or a number in the
  frontend.
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
- Never commit `data/upstream/`, `data/context/` or any database file.

## Delegating

Mechanical work (formatting, a scoped test file, a doc pass) can go to a
cheaper model. The ingest, the alias map and the rescore are cross-cutting:
review those changes with a stronger model before merging.
