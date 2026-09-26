# AGENTS.md — DataAgentBench explorer

The source of truth for how this project is built and why. `CLAUDE.md` points
here. `DESIGN.md` governs anything visual. The plan this build was approved
against is `.lavish/s00_dab-explorer-init-plan.html` (decisions A, B, C and the
M0–M4 scope are recorded there).

## 1 · What it is — the DAB benchmark, ingested, indexed and explorable

[DAB](https://github.com/ucbepic/DataAgentBench) (DataAgentBench, UC Berkeley
EPIC + Hasura PromptQL, [arXiv 2603.20576](https://arxiv.org/abs/2603.20576))
is a data-agent benchmark: natural-language questions over two to six
databases at once (SQLite, DuckDB, PostgreSQL, MongoDB), each with a
`ground_truth.csv` and its own `validate.py`. This project:

1. shallow-clones the upstream repo with LFS skipped (`make upstream`), so no
   database byte is downloaded;
2. ingests the text layer into a committed JSON index (`make ingest`): the 12
   leaderboard datasets, their 54 queries, gold, validator source, schema
   descriptions, hints, the manifest, the site's leaderboard, and normalised
   copies of the 9 answer files committed upstream (14,480 answers);
3. judges every committed answer with its query's validator (`make rescore`)
   and commits the per-query summary, which reproduces the site's Pass@1;
4. serves a read-only explorer (React + FastAPI) over all of it.

The agent build (§8, plan `.lavish/s01_agent-blueprint.html`, approved for
M0–M3 on 2026-09-21) adds one Claude Agent SDK analyst over the same 54
questions, the data re-hosted in Postgres, a generated-then-curated context
pack, and runs judged by the same validators. Six things call a model — the
eval agent, the curator, the optimiser, the reader, the reviewer and
`llm_extract` — all on the subscription through the Agent SDK (`CLAUDE.md`).

## 2 · Decisions, and the reasons

| Decision | Choice | Why |
|---|---|---|
| Scope (B) | the 54 leaderboard queries in 12 datasets; the 50 queries in 5 unreleased datasets (`civic_unstructured`, `cve`, `imdb`, `krama`, `usaspending`) are recorded as a count only | the leaderboard scores the 54; the 50 have gold but no published trial, no README row and no rubric entry — "keep it to the 54 and expand later" (review, 2026-09-20) |
| Ingest (A) | text layer only; `GIT_LFS_SKIP_SMUDGE=1` | 322 KB is everything the explorer shows; the databases are 8.35 GB for the 54 and belong to the agent build, per dataset |
| Redistribution (C) | commit `data/index/` and `data/answers/` with `ATTRIBUTION.md` and the pinned source commit | upstream has no LICENSE file; the app must work from a bare clone; removed on request |
| Dataset key | folder name lower-cased + the site's own `DATASET_ALIASES` | three spellings upstream (`deps_dev` / `DEPS_DEV_V1` / `deps_dev_v1`); 14,480 of 14,480 answer rows join |
| Validator classification | four styles by source text (`levenshtein` → `ground_truth.csv` → `import re` → substring) | the validator is the eval; the CSV is a copy for 54 of 54 in scope |
| Rescore | one worker process per (query, answer file), `signal.alarm` per call, 30 s | nine levenshtein validators are O(n·m) pure Python against answers up to 13.8k chars; the single-process run took >10 min |
| Pass@1 | report micro (rows) and macro (mean over datasets of mean per-query rate) | the site's number is the macro one; the two differ by up to 6 points |
| Reproduction test | our macro per-dataset numbers must match the site's stratified tables to two decimals, except `deps_dev_v1` | the site re-scored 2026-06-12; DEPS_DEV_V1 q1's validator was revised 2026-08-18 (issue #86) |
| Frontend | React 18 + Vite + TS, plain CSS on `tokens.css` | the Field Guide brief (`DESIGN.md`); no Tailwind/DaisyUI |
| Python | 3.12, uv, ruff, mypy strict, pytest | the workspace's rules |

## 3 · Layout

```
data/upstream/        gitignored: the shallow clone (`make upstream`)
data/index/           committed: source.json · datasets.json · queries.json · validators.json
                      manifest.json · leaderboard.json · trials.json · ATTRIBUTION.md
                      (verdicts.jsonl is per-row and gitignored)
data/answers/         committed: the 9 answer files, normalised to {id, run, answer}
data/context/         gitignored: databases, if a later build downloads them
src/dab_bench/
  config.py           paths + Settings (no keys)
  cli.py              `dab upstream | ingest | rescore | stats | serve`
  data/               aliases.py (keys, the released 12, the 9 answer files) · upstream.py · ingest.py · index.py
                      load.py (the three engines into one schema) · meta.py (the question set's copy,
                      schema dataagentbench_meta, granted to nobody: it holds gold)
  eval/               validators.py (import + alarm-bounded call) · rescore.py (pool, summary, site check)
  serving/app.py      FastAPI over the index + SPA fallback
frontend/             Vite + React; src/tokens.css verbatim from DESIGN.md; scripts/design_lint.mjs
  src/routes.tsx      every address, as data; old ones are redirect loaders (routes.test.tsx drives it)
  src/lib/url.ts      the URL grammar: one id per thing, path = subject, query string = lens
  src/pages/          Overview · Datasets · Dataset · Query · Validators · Leaderboard · Runs · Run · TracePage · Agent · Golden
  src/lib/queries.tsx QueryTable: one table for all 54 and for one dataset's, so the columns cannot drift
tests/                fixture-tree ingest · aliases · validator runner with timeout · API on the
                      committed index · trials reproduce the site
.github/workflows/    ci.yml (python + frontend; no upstream clone in CI)
```

## 4 · Commands

```
make setup            uv sync + npm ci
make upstream         shallow clone → data/upstream (DAB_UPSTREAM_COMMIT pins a commit)
make ingest           data/upstream → data/index + data/answers
make rescore          validators over every committed answer → data/index/trials.json  (WORKERS=4 TIMEOUT=30)
make stats            the numbers the README quotes
make dev              API on :8091 (with the built SPA when frontend/dist exists)
cd frontend && npm run dev     the explorer on :5173, proxying /api to :8091
make build            frontend/dist
make test · make lint · make fmt
```

## 5 · The index, precisely

- `source.json` — repo, commit, ingest time, totals upstream (17 / 104), in
  scope (12 / 54), deferred (5 datasets / 50 queries), answer rows and how
  many failed to join (must be 0), ingest warnings.
- `queries.json[i]` — `id` (`crmarenapro/1`), `dataset_key`, `query_id`,
  `question` (verbatim), `gold_text`, `gold_lines`, `validator {style, lines,
  reads_gold_file, source}`, `released`, `on_site`, `site_text_matches`
  (false for `github_repos/2`, whose wording was revised in the repo),
  `footnote` (the site's methodology note for `deps_dev_v1/1` and the three
  `patents` queries).
- `datasets.json[i]` — key, folder, queries, engines, `dbs[]` from
  `db_config.yaml` with bytes from the manifest (or the file in git),
  `description`, `hints`.
- `leaderboard.json` — the site's file, plus `answer_files[]` mapping each
  committed answer file to its leaderboard row and stratified column.
- `trials.json` — `summary` (rows, timeouts, never-passed, under-10%),
  `per_file` (micro, macro, per dataset), `per_query` (per file: n, passed,
  timed out, three pass and three fail example row indices with the
  validator's reason), `site_check` (ours vs the site per dataset).

The API joins `per_query` example indices back to `data/answers/` so the Query
page shows the answers verbatim. Nothing in the frontend is hand-maintained.

## 6 · What the numbers mean

- "Pass rate" on a query or dataset page is over every committed trial
  (265–270 per query: 5 × 50 ReAct + 4 × 5). It is a micro average and says
  how often the field gets that question, not any one agent's score.
- A leaderboard Pass@1 is the macro average; `per_file[].macro` reproduces it.
- "Not scored" means no trial, never zero. The deferred 50 never get a number.

## 7 · The SQL-answer challenger and one round of the loop (s06, 2026-09-24)

Plan `.lavish/s06_golden-from-gold-and-hints.html`, decisions D26–D31:

- **`agents/v1_sql/`**: the prompt is `system.md` + the code-built tables map + the
  upstream description and hints, verbatim (`pack: false`, `hints: true`); three
  tools (`query_db` without `save_as`, `describe_table`, `submit_answer`); no
  sandbox. `submit_answer(sql, mode, answer?, step?)` re-runs the SQL as
  `dab_agent`: mode `pass_through` makes the rendered result the answer, `derived`
  keeps the model's answer and its one-line step. `results.jsonl`, the trace and
  MLflow record `agent_sql`, `agent_result`, `mode`, `step`.
- **The scorecard** (`eval/scorecard.py`, `dab diagnose <run>`): answer (the
  validator, over 54) · SQL (the agent's result against the golden's, where a golden
  exists) · decision (mode against the golden's kind), a category per failure from
  the result diff and a `sqlglot` structure diff; `runs/<id>/scorecard.json`.
- **The optimiser** (`agents/optimiser/`, Sonnet 5 medium; `dab optimise <run>
  --into <version>`): one isolated session per dataset with failed *train* questions
  (`data/splits/train.json`, 33 of the 49 goldened; 16 held out) writes
  `agents/<version>/datasets/<ds>.md`, which the prompt carries under "Notes for
  this dataset"; one cross-dataset pass may edit `system.md` (D31 A). Every write
  passes `eval/guards.py`. `agents/<version>/optimise.json` records the round.
- **Promotion** (`dab promote`, D30): the most answers passed of the 54 among the
  versions' newest complete runs wins; a tie keeps the incumbent;
  `agents/promotions.jsonl` keeps every verdict; the MLflow prompt
  `dataagentbench.system` carries the `champion` alias.
- **The explorer**: the Optimise tab (`/optimise`, a round at `/optimise/<version>`,
  `eval/rounds.py`) shows every round as diagnostic → proposal → outcome, with the
  version lineage and each question before and after; the Runs tab opens with the
  champion over time (the reigns in `agents/promotions.jsonl`). Both tabs draw the versions
  with one figure (`frontend/src/lib/versions.tsx`): every version in build order, and under
  each how it was made (`eval/rounds.version_change`): an optimise round, a build change or
  a model change, and the version it came from.

### Round 2: the statement is the goal (s08, 2026-09-25)

Plan `.lavish/s08_round2-sql-then-sonnet.html`, decisions D32–D37. Round 1 lifted answers
24 → 30 of 54 but SQL only 13 → 18 of 49 (held out 1 → 2 of 16): it taught data facts, and
its diagnosis named a `sqlglot` category rather than the part of the statement that broke.

- **The ledger** (`eval/ledger.py`, `agents/reader/`, D33): `dab diagnose <run> --ledger`
  has a Sonnet 5 reader describe each statement as seven steps in words (sources, keys,
  parse, filter, metric, rank, shape). A golden's lines are cached by golden id in
  `dataagentbench_meta.golden_ledger`; for every trial whose SQL fails, the agent's lines,
  a verdict per step and the step it `breaks_at` go to `runs/<id>/ledger.json`, and the
  trial's category becomes `breaks at <step>`.
- **The optimiser** (D32 B): component sessions, one per step at which failed training
  statements break, read those questions across every dataset and write that step's
  section of an SQL playbook in `system.md` (skeleton `agents/optimiser/playbook.md`,
  prompt `agents/optimiser/component.md`, tool `write_section`, at most 600 characters a
  section, `system.md` at most 8,000); dataset sessions write
  the notes as before, led by the ledger, up to 2,000 characters. The cross-dataset
  system pass is not run. Every write passes the same guard.
- **Plan first** (D34): the playbook asks for the plan before the first query;
  `agent.yaml` `plan: true` makes `submit_answer` require `plan`, the statement's seven
  steps, recorded in `results.jsonl`, the trace and MLflow.
- **Sonnet after the round** (D35 A): `v4_sql` is `v3_sql` with `model: sonnet` and
  `measured_against: v3_sql`, so the prompt's lift (v2 → v3, both Haiku) and the model's
  (v3 → v4) are measured apart.
- **Promotion** (D36 B): the most SQL passed of the questions with a golden wins; answers
  of the 54 break a tie; then the incumbent; then the older run. Replaced by D46 (s14).
- **The Optimise tab** (D37 A): the loop as seven clickable stages with the round's own
  counts, the rounds over versions with SQL first, and a round opened as a component
  matrix, one card per session and held-out SQL first.

Outcome (receipts `.lavish/s09_…`, `s10_…`): the same prompts on Haiku, Sonnet 5 and Opus 5.5
scored SQL 19, 27 and 28 of 49; round 3 on Opus (reader and optimiser on Opus too, `--model
opus`) wrote `v6_sql`: SQL 33 of 49, answers 46 of 54, held-out SQL flat at 4 of 16. v6_sql
was promoted over v4_sql.

### Round 4: every error, as the leaderboard does (s11, 2026-09-25)

Plan `.lavish/s11_leaderboard-protocol-v7.html`, decisions D38–D41. The leaderboard has no
holdout: it scores the 54, and every top-12 entry is marked "Tuned prompt ✓" (built from
studying them). Three rounds had lifted training SQL +10 of 33 and held-out SQL +1 of 16.

- **Every error read** (D38 B): `dab optimise --train all` reads every error of the source
  run, held-out questions and wrong answers without a golden included (those reach their
  dataset session with the agent's answer and the validator's fail, never its text). No
  cross-fit for v7: its score on the 54 is in-sample. `dab crossfit` (built on request)
  scores the same round out of sample: k folds by dataset, each fold's round excludes that
  fold and its prompt (`<version>_f<i>`, `crossfit_of` in `agent.yaml`, never listed or
  promoted) answers only it; `runs/<run>/crossfit/<version>.json`.
- **One trial** (D39): 54 × 1 for v6 and v7, as rounds 1–3; D41 falls away and D36 stands.
- **Guards G1–G4 with v7** (D40 B), `dab optimise --strict`: G1 an Opus reviewer
  (`agents/reviewer/`, `eval/review.py`) refuses text that hands over a decisive value or
  interpretation (the rubric's §2.2); G2 every gold value searched in the finished text,
  a hit reverting that unit (`guards.audit`); G3 a playbook section only where two or more
  errors break, its rationale citing two by id; G4 no text naming a question.
- **The leaderboard's number** beside the rule: Pass@1 (the mean over datasets of each
  one's pass rate) in `dab promote`, the rounds table and the Optimise headline;
  `dab export-submission <run>` writes the answers in the leaderboard's format.

v7 tied v6 on answers (46/54) and lost SQL (30/49 against 33/49); v6 kept the title.

### Round 5: the optimiser reads the history (s13, 2026-09-25)

Plan `.lavish/s13_v8-history-from-mlflow.html`, decisions D42–D45 (all A). 7 of v6's 20
failing questions had passed under an earlier version; 4 of them first failed in v6, and
the round that made v6 read none of them (they were passing). v7 read them with no sign of
that. So:

- **The champion lock**: `dab optimise` with no run takes the champion's newest full run
  (`promote.champion_run()`); a run of another version is refused (`NotChampionError`).
  `dab crossfit` passes its own run and reads no history.
- **Round outcomes and session traces in MLflow** (`eval/outcome.py`): `dab promote` tags
  each round version's MLflow run `outcome=won|lost|pending` with `outcome.json` (answers and
  SQL against its parent, every question gained and lost, where each lost statement
  breaks); each optimiser session is a trace (`kind=optimise_session`).
  `dab mlflow-backfill` put rounds 1–4 there, with no model call.
- **The history** (`eval/history.py`, D42 A: read from MLflow, parity-checked against the
  folders): the champion's lineage and the rounds from it that lost; per question the
  timeline, each flip labelled (a prompt change for it, a model switch, or no change to its
  notes or break-step section: noise), and for a regressed question the diffs since its last
  pass and the statement that passed (D44 A). Written to `runs/<run>/history.json`.
- **What the sessions read** (D43 A, optimiser only): each failed question's history block
  and each lost round's block for the same dataset or step; the optimiser's prompts gained
  one paragraph on reading them. v8 = v7's recipe plus the history (D45 A).

v8 against v6: answers 48 of 54 against 46, Pass@1 0.904 against 0.891, SQL 31 of 49 against 33
(McNemar on answers +3/−1, p = 0.63; on SQL +2/−4, p = 0.69). D36 kept v6; D46 promoted v8.

- **Promotion by the leaderboard's number, behind a leak gate** (D46, 2026-09-25, the
  owner's call): a challenger takes the title only when the round that made it ran guards
  G1–G4 (`--strict`; a model switch is judged by the version it copied, a base version saw
  no gold) and G2 finds no gold value in its `system.md` or any notes (`promote.leak_gate`).
  Of those standing (the incumbent always stands), the highest Pass@1 wins; answers of the
  54, then SQL of 49, break a tie; then the incumbent; then the older run. v2–v5 are barred
  (rounds 1–3 ran the literal guard only), and v6, no longer champion, is barred with them.
  v8 carries 7 of the 10 units of v6's text that the s12 G1 audit judged decisive, unchanged
  (none is a gold value); it rewrote the other three under G1.

## 8 · The agent build — decisions, layout, contract

Decided in the s01 review (all queued by the reviewer):

| Decision | Choice | Why |
|---|---|---|
| Dataset known upfront, one agent | the dataset is a required input (as upstream `--dataset`); one `system.md` for all 12, parameterised by a per-dataset pack | no team on the leaderboard triages; 13/15 documented rows are one agent |
| D7 · where the facts go | in the **system prompt**: `system.md` + `<ds>/summary.md` + `pitfalls.md` + upstream description (+ hints when `--hints`); the user message is the question alone | same cache prefix, fingerprint stays `sha256(system.md + agent.yaml + helper.py)`, `context_sha` pins the pack; Camber's precedent |
| The pack | `dab context build` (code: schema, profile, samples, measured joins) then `dab context curate` (Sonnet 5, once per dataset, never sees a question) writes `summary.md` + `pitfalls.md` | the knowledge base must be legitimate under the rubric and reviewable as a diff |
| D1 · delivery | summary + pitfalls injected; depth on demand via `read_context` / `search_context` | every trial starts oriented; the full pack stays out of the prompt |
| D6 · data | all 12 datasets re-hosted into one Postgres schema `dataagentbench`, tables `<dataset>_<table>`, Mongo as typed columns + `doc jsonb`; table families (stockmarket's 2 753 tickers) also get a union table `*_all` | one dialect, one read-only role (`dab_agent`, 60 s statement timeout); the leaderboard's top rows all re-host |
| Postgres location | database `dab` on nmp-central-ai's central Postgres (:5432, one database per project — platform D13), since 2026-09-22 | rule zero holds; `roles.sql` ran unchanged against the new database; the old compose server (:5433) was dumped, restored, verified table-for-table and deleted (platform D14) |
| D3 · Python | docker `--network none`, one container per run, a fresh process per call; data arrives as parquet on `/work` via `query_db(save_as=)` | rubric-grade isolation; no credential inside the box |
| D5 · observability | central MLflow only, experiment `dataagentbench/evals`, platform tags, fail-fast `/health` preflight; one run + one trace per trial built from the message stream (tags: run_id, dataset, query, trial, passed, reason, agent, fingerprint, context_sha) | the loop reads failures from `mlflow.search_traces`; the registry entry is `infra/registry.P6.yaml` |
| D4 · billing | the subscription through the Agent SDK's `claude` child | as the siblings; a rate-limited trial is unscored and `--resume` finishes it |
| D0 · smoke | the median-difficulty query per dataset (`data/splits/smoke.json`) | a first Pass@1 preview rather than a harness check |
| D2 · versions | v0 measured and installed as champion (`agents/champion`); v1 is what the loop promotes | this build ships the loop's scaffolding, not a hand-written v1 |
| Model | Haiku 4.5 at effort medium for eval runs; Sonnet 5 for the curator | the dollar profile; measured against the Max 5× window, a 54 × 5 Haiku run is ≈ 83 % of one window |

Layout added by this build:

```
agents/v0/            system.md (behaviour) · agent.yaml (frozen budgets) · helper.py (empty surface)
agents/curator/       system.md · agent.yaml — runs once per dataset, never inside an eval
agents/champion       one line naming the champion version
data/context/<ds>/    committed pack: tables.json · schema.md · profile.json · samples/ · joins.md/.json ·
                      description.txt · hints.txt · summary.md · pitfalls.md · curation.json
data/splits/          smoke.json (12 ids); `all` is the index
infra/                roles.sql (applied to database `dab` on the central Postgres) · sandbox.Dockerfile
runs/<id>/            gitignored: run.json · results.jsonl · traces/<ds>_<n>_t<k>.json · agent/ (incl.
                      system.<dataset>.md, the composed prompts) · context/<ds>/ copies
workspace/<run>/      gitignored: the sandbox's /work, one folder per trial
src/dab_bench/
  data/stores.py · download.py · load.py · pg.py      the store map, HF download, the three load paths, roles
  context/build.py · curate.py                        the generated half; the curator session
  agent/llm.py · versions.py · prompt.py · tools.py · sandbox.py · session.py
  eval/splits.py · score.py · runner.py               splits; TrialResult, summary + `profile()` (p50/p95); `dab eval`
  tracking/mlflow_log.py · tracing.py                 the run record on MLflow; one trace per trial
  serving/app.py                                      `/api/runs` = the board (roles derived, profile per run); `/api/runs/<run>/<ds>/<n>/t<k>` adds the span tree
frontend/src/pages/Runs.tsx · Run.tsx · TracePage.tsx · lib/runs.tsx   the board, one run vs the champion, the span waterfall
frontend/src/pages/Agent.tsx · lib/agent.tsx        the Agent tab: the system graph, the node panel + tool form, the replay
```

**One tool table.** `agent/tools.py` holds `TOOL_SPECS` (name, description,
JSON schema, backend) and one body per tool; `call_tool(state, name, args)` is
the only way a body runs. The trial's MCP server wraps it; the explorer's
playground (`POST /api/agent/tools/<name>`) calls it. Adding a tool = one spec
+ one body; the graph, the form and the trace spans follow.

**Roles are derived, never declared.** The champion is the newest scored
full-split run of the agent `agents/champion` names that has no
`challenger_of`; every other full-split run is a challenger (older champion-agent
runs: superseded); smoke runs never hold the title. The explorer's span waterfall
is rebuilt from `traces/<key>.json` with the same rules as `tracking/tracing.py`,
so it matches the MLflow trace without reading MLflow. Embedding the MLflow trace
view needs the central server started with `MLFLOW_SERVER_X_FRAME_OPTIONS=NONE`;
the explorer probes the header once and shows the toggle only then.

The result row (`results.jsonl`) carries `query_id · dataset · trial · answer ·
passed · reason · n_turns · duration_ms · cost_usd · input_tokens ·
cache_read_tokens · cache_creation_tokens · output_tokens · tool_calls · error ·
terminal_reason · timed_out · rate_limited · trace_file · mlflow_trace_id`.
`run.json` carries the agent, its fingerprint, the combined `context_sha`, model,
effort, split, trials, hints, `challenger_of`, the summary (micro, macro,
per dataset, per query, tokens, cost) and `mlflow_run_id`.
