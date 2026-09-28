# CLAUDE.md — DataAgentBench explorer

> Read [`AGENTS.md`](./AGENTS.md) first: what this is, the decisions, the layout,
> the index. [`DESIGN.md`](./DESIGN.md) governs anything visual (explorer, Lavish
> artifacts, README figures). This file is a pointer plus the rules that bite.

## Quick reference

- `make setup` · `make upstream` · `make ingest` · `make rescore` · `make stats`
- `make dev` + `cd frontend && npm run dev` (explorer on :5173, API on :8091)
- agent build: `make platform-up` · `make db-roles` · `make data` · `make context` ·
  `make curate` · `make sandbox` · `make eval SPLIT=smoke|all TRIALS=n`
- the loop (s06, s08, s11, s13): `dab eval --agent <version> --split all` ·
  `dab diagnose <run> --ledger [--model opus]` ·
  `dab optimise --into <version> [--model opus] [--train all --strict]` (the champion's
  run; it builds and reads the history) · `dab history [--parity]` · `dab mlflow-backfill` ·
  `dab crossfit <run> --prefix <version>` · `dab promote` · `dab export-submission <run>`
- `uv run pytest -q` · `make lint` · `make fmt` (`DAB_TEST_PG=1` adds the live role test)

## Rules

- **Only six things call a model**, all through the Agent SDK on the
  subscription: the eval agent (`dab eval`), the curator (`dab context curate`),
  the optimiser (`dab optimise`, s06), the reader (`dab diagnose --ledger`, s08,
  never inside a trial), the reviewer (guard G1 inside `dab optimise --strict`,
  s11, never inside a trial) and `llm_extract` inside a v0 trial (the SQL versions have
  no `llm_extract`). `agent/llm.py` is the one place a model is
  named; `require_live()` refuses to start with a per-token key present.
  The explorer, the ingest, the rescore and the context *build* never do —
  the Agent tab's playground runs every tool *except* `llm_extract`, which
  stays display-only (decision D8-A; `DAB_PLAYGROUND_LLM=1` is the only way
  to change that, and it is not wired).
- **A session sees its prompt and its `dab` tools, nothing else.**
  `agent/isolation.py`: every eval, curator, optimiser, reader and reviewer session starts in an empty
  directory outside the repo, with auto-memory, CLAUDE.md and the `agents-md`
  plugin off, no settings sources, no built-in tools and a strict MCP config.
  The CLI's `init` message is recorded on each trace, and any tool, server or
  plugin beyond the version's own stops the run. `dab isolation-check` (one
  short turn) also reads the session transcript against an allowlist of the
  context the CLI adds. The account email and (CLI 2.1.281) organisation id are on
  that list because the CLI offers no switch for them; neither reaches a trace
  or MLflow. The CLI's built-in `agents-md` and `telemetry` plugins are off. Each trial's
  `execute_python` runs in its own container with only its own `/work`
  folder mounted (`tests/test_sandbox.py`).
- **The pack is the knowledge base, and it is legitimate by construction.**
  `dab context build` is code; the curator never sees a question;
  `tests/test_context.py` asserts no question text lands in `summary.md` or
  `pitfalls.md`. Never hand-edit the curated files to fit a query — re-curate,
  or change the curator's prompt (`agents/curator/system.md`).
- **The run folder is the record; MLflow is the index.** `runs/<id>/` is what
  the explorer, the profile and a compare read. MLflow (central,
  `dataagentbench/evals`) is linked, never read back, with one exception (s13, D42 A):
  `dab history` builds the optimiser's history from MLflow's copies (eval runs, round
  runs with their `outcome`, session traces), and `dab history --parity` holds it equal to
  the one built from the folders. MLflow down stops a round; it never falls back. Never start a local
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
  hard-code a dataset, a query or a number in the frontend. Two routes
  execute, both on the read-only role. The playground,
  `POST /api/agent/tools/<name>`, runs the trial's own tool bodies
  (`call_tool`) and the network-off sandbox; it writes no run folder and no
  MLflow trace, only /work files under `workspace/playground/`. Golden SQL,
  `POST /api/golden/<ds>/<n>[/run]`, runs one SELECT as `dab_agent` and judges
  it with the question's validator.
- **Golden SQL is curated, and it encodes answers.** A person saves every
  golden in the Golden tab. The editor may start from the SQL a run's agent
  wrote for that question (the run picker; the champion by default), but nothing
  saves a golden without someone running and saving it, and each save records
  where its SQL started (`source`). A question's golden starts empty.
  Proposals (`dab golden-propose <folder>`, table `golden_proposal`) are SQL
  written outside the tab, run and judged before they land; they are shown
  for review and are never goldens until someone saves one. An *evidence*
  golden (D23) is intended for a judgment question such as crmarenapro/1, 2,
  3, 6, 7: its SQL returns what a reader needs, the expected answer is
  recorded beside it, and the validator is not applied. The kind is chosen by
  the curator in the Golden tab, not restricted in code to those five — any
  question may be saved as evidence. A golden is one SQL statement: no Python. Saves append to `dataagentbench_meta.golden_sql` (the
  newest is current, and nothing is ever dropped; `make db-reset` leaves the
  meta schema alone). `dab_agent` is refused there (`tests/test_golden.py`).
  A golden never reaches a trial's prompt, the pack, the curator or a proposer.
  The one exception is the optimiser (s06, D29 A): it sees the golden SQL and the
  result diff of the *train* questions (`data/splits/train.json`), never a held-out
  one, and every note it writes passes `eval/guards.py` (no run of 8 question words,
  no gold value written literally, no run of 6 golden SQL tokens, ≤ 1,500
  characters; from s08, 2,000 for notes, 600 for a playbook section and 8,000 for
  `system.md`) or is refused. From s11 (D38) a round may read every error of the 54
  (`--train all`): there is no held-out set then, and the version's score on the 54 is
  in-sample, as every leaderboard number is; `dab crossfit` measures the same round out of
  sample with fold prompts (`crossfit_of` in `agent.yaml`) that are never listed or
  promoted. `--strict` (D40 B) adds guards G1–G4: an Opus reviewer that refuses text
  handing over a decisive value or interpretation (the leaderboard rubric's §2.2; it sees
  gold answers, never writes a prompt), an audit of every gold value in the finished
  text, two or more errors behind every playbook section, and no text naming a question.
  `tests/test_s11.py` holds every version's prompt to the audit. From s14 (D46) `dab promote`
  lets a challenger take the title only through that gate (its round ran G1–G4, and G2 finds
  no gold value in its prompt), then ranks by Pass@1; the incumbent always stands. From s13 a round starts
  only from the champion's run (`dab optimise` refuses another) and its sessions read the
  history (`eval/history.py`): each failed question's answer and SQL under every version,
  what each round changed, the statement that last passed a regressed question (the
  agent's own; a past answer is never read, as for a question with no golden it is the
  gold answer), and every round from the champion that lost to it. The history is input
  to the optimiser only, and what it writes passes the same guards. The scorecard (`dab diagnose`) reads goldens after a
  run; nothing it computes reaches a trial. The reader (s08, `eval/ledger.py`)
  describes goldens and failed statements in words, seven steps each: its lines
  are stored beside the golden (`dataagentbench_meta.golden_ledger`, refused to
  `dab_agent`) and the run (`runs/<id>/ledger.json`) with any gold value written
  literally redacted, and never enter a prompt; the optimiser reads them, and what
  it writes from them passes the same guard.
- **One address per thing** (`frontend/src/lib/url.ts`; test
  `frontend/src/routes.test.tsx`). One id, spelled the same everywhere:
  question `deps_dev_v1/1`, trial `deps_dev_v1/1/t1`; the trace file's flat
  name stays on disk (`aliases.trace_stem`) and never reaches a URL. The path
  names the subject (`/datasets/deps_dev_v1/1`, `/runs/<run>/deps_dev_v1/1/t1`,
  `/agent/champion`); the query string holds the lens, written readably by
  `search()`. Picking from a list opens the detail in place through a nested
  route (`/golden/<ds>/<n>`). Build every link with the helpers; an address that
  changes gets a redirect loader in `routes.tsx`, never a 404.
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
- **A leaderboard file read from a PR is a reference, never pooled.** An
  `ANSWER_FILES` entry with `pr` + `commit` is fetched by `make upstream` and
  read with `git show`, so the checkout stays at the ingested commit. It is
  rescored and comparable on the Runs tab (`lb:<name>`), but `pooled: False`
  keeps it out of each query's published rate. Its overall Pass@1 must still
  reproduce the site's, or carry a reason in `TOLERATED_OVERALL`.
- **Visuals follow DESIGN.md**: tokens verbatim, assertion headings, one `<em>`
  per page, every number with its baseline. Never the Tailwind/DaisyUI fallback.
- Never add `.lavish/` to `.gitignore`.
- Never commit `data/upstream/`, `workspace/`, a run's `traces/` or any database file.
  `data/context/` (the pack, text only) **is** committed, and so are a run's four record
  files (`run.json`, `results.jsonl`, `scorecard.json`, `ledger.json`): they are what the
  case study and every quoted number cite. `data/golden/coverage.json` is the committed
  view of golden coverage — a status per question, no SQL text — written by
  `dab golden-coverage`; re-run it after saving goldens.

## Delegating

Mechanical work (formatting, a scoped test file, a doc pass) can go to a
cheaper model. The ingest, the alias map and the rescore are cross-cutting:
review those changes with a stronger model before merging.
