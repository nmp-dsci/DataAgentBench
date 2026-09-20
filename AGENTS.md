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

Agents, evals of our own, the loop and optimisation are later builds on this
skeleton. **This build calls no model and needs no key.**

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
  eval/               validators.py (import + alarm-bounded call) · rescore.py (pool, summary, site check)
  serving/app.py      FastAPI over the index + SPA fallback
frontend/             Vite + React; src/tokens.css verbatim from DESIGN.md; scripts/design_lint.mjs
  src/pages/          Overview · Datasets · Dataset · Queries · Query · Validators · Leaderboard
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

## 7 · Later builds

Per-dataset `make data` and the DB servers; one Claude Agent SDK agent with
the benchmark's four tools (list DBs, query DB, execute Python, return
answer), given each dataset's config and description per run as the reference
`run_agent.py` does — never an agent per dataset; `runs/` scored by the same
`eval/` plane; MLflow; the error loop and gate; a demo deploy. The explorer
gains Runs and Trace pages and nothing else moves.
