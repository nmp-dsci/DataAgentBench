# DataAgentBench explorer

An explorer over the [DAB](https://github.com/ucbepic/DataAgentBench)
benchmark (DataAgentBench, UC Berkeley EPIC + Hasura PromptQL,
[arXiv 2603.20576](https://arxiv.org/abs/2603.20576)): its datasets,
questions, gold answers, validators and the published trials, ingested from
the upstream repo into a committed index and served as a small app — and, since
the agent build (plan `.lavish/s01_agent-blueprint.html`), one Claude Agent SDK
analyst that answers the 54 questions over the same data re-hosted in Postgres,
judged by the same validators, with every run and trace on the central MLflow.

## 1 · What it shows — 54 questions, every one with gold, and who has beaten them

DAB's leaderboard set is 54 natural-language questions over 12 datasets, each
asked across two to six databases in up to four engines (SQLite 10 datasets,
DuckDB 8, PostgreSQL 5, MongoDB 2). Every query ships a `ground_truth.csv` and
its own `validate.py`. The upstream repo also commits nine answer files from
leaderboard runs — 14,480 answers in all — and this project judges every one
of them with its query's validator.

| | |
|---|---|
| queries in scope | **54** across 12 datasets (upstream holds 104 across 17; the 50 in five unreleased datasets have no leaderboard entry and are deferred) |
| with gold and a validator | **54 / 54** |
| published answers judged | **14,480** in 9 files, in 166 s with 6 workers, 2 timeouts |
| queries no published run has ever passed | **3** of 54: `agnews/3`, `pancancer_atlas/1`, `patents/1` (0 of 265–270 trials each) |
| queries under 10% | **15** of 54 |
| database bytes behind the 54 | **8.35 GB**, none downloaded here (322 KB of text is the whole index input) |

Source: `data/index/` at upstream commit `0290945`, via `make stats`.

## 2 · Why trust the rescore — it reproduces the site's own numbers

Each committed answer file, judged locally, gives the same Pass@1 the site
publishes (mean over datasets of each dataset's mean per-query pass rate):

| Answer file | Site Pass@1 | Ours, macro | Ours, micro (over rows) |
|---|---|---|---|
| Claude Opus 4.6 ReAct (5 trials/query) | 0.5551 | 0.5551 | 0.6074 |
| PromptQL + Gemini 3.1 Pro (5) | 0.6000 | 0.6000 | 0.6259 |
| PromptQL + Claude Opus 4.6 (5) | 0.5933 | 0.5933 | 0.6667 |
| Gemini-3-Pro ReAct (50) | 0.4663 | 0.4663 | 0.4859 |
| GPT-5-mini ReAct (50) | 0.3663 | 0.3663 | 0.4144 |
| GPT-5.2 ReAct (50) | 0.2991 | 0.2991 | 0.3378 |
| Kimi-K2 ReAct (50) | 0.2925 | 0.2922 | 0.3454 |
| Gemini-2.5-Flash ReAct (50) | 0.1049 | 0.1049 | 0.1252 |

Source: `data/index/trials.json` `per_file` and `leaderboard.json`. The only
per-dataset gap is `deps_dev_v1`, whose query 1 validator the site revised on
2026-08-18 after its stratified tables were computed; `tests/test_trials.py`
tolerates that dataset and holds every other to two decimals.

## 3 · Run it

```bash
make setup                       # uv sync + npm ci
make dev                         # API on :8091, reading the committed index
cd frontend && npm run dev       # the explorer on :5173
```

That works from a bare clone: the index and the answer copies are committed.
To rebuild them from upstream:

```bash
make upstream                    # shallow clone, LFS skipped (no database bytes)
make ingest                      # → data/index/*.json, data/answers/*.json
make rescore                     # → data/index/trials.json (about 3 minutes)
make stats
```

## 3b · Run the agent

```bash
make platform-up                 # nmp-central-ai's stack: Postgres :5432 (database `dab`) and MLflow :5000
make db-roles                    # schema dataagentbench + roles dab_owner / dab_agent inside database `dab`
make data                        # download the 12 datasets (8.4 GB, sha256-verified) and load them: 2 811 tables
make context                     # the generated half of the context pack (no model)
make curate                      # the curator agent writes summary.md + pitfalls.md per dataset (≈ $1.40 once)
make sandbox                     # the execute_python image (python:3.12-slim, no network)
make eval SPLIT=smoke            # v0 on one median-difficulty query per dataset (12 trials, ≈ $1.3)
make eval SPLIT=all TRIALS=1     # all 54 once
uv run dab runs list · uv run dab runs profile <run> · uv run dab eval --resume <run>
```

Eval runs bill the Claude Max subscription through the Agent SDK's `claude`
child (`require_live()` refuses a per-token key). A run that hits the
subscription's 5-hour window records those trials as *rate limited, not scored*
and `--resume` finishes them after the reset.

| smoke, v0 (`20260921T042451Z_v0_smoke_haiku`) | |
|---|---|
| scored | **7 / 12 pass** (macro 0.58; the field's average on this set is ≈ 0.33); 4 trials were rate-limited by the subscription window mid-run and finished with `--resume` |
| cost | **$2.17** for 12 trials; p50 $0.09, one outlier (deps_dev_v1/1: 22 turns, 637 s, $1.02) |
| per trial, p50 | 11 turns · 23k fresh input · 89k cache-read · 5.8k output · 60 s |
| passed | bookreview/2, crmarenapro/6, stockindex/1, github_repos/4, music_brainz_20k/1, yelp/2, pancancer_atlas/3 |
| failed | agnews/1, googlelocal/4, stockmarket/3, patents/2, deps_dev_v1/1 |

| v0 wide, all 54 once (`20260921T064521Z_v0_all_haiku`) | |
|---|---|
| scored | **27 / 54 pass**, macro **0.44** (mean over datasets; micro 0.50) — Haiku 4.5, effort medium, no hints, one trial per query, 38 min at 4 workers |
| for scale | the published ReAct baselines with hints: Opus 4.6 0.555, Gemini-3-Pro 0.466, GPT-5.2 0.299 (5–50 trials each, §2) |
| cost | **$8.96**; p50 $0.07 per trial, p90 $0.73 (four trials hit the 900 s timeout: agnews/1, /3, /4 and deps_dev_v1/1) |
| per dataset | bookreview 3/3 · crmarenapro 9/13 · yelp 4/7 · stockmarket 3/5 · stockindex 2/3 · pancancer_atlas 2/3 · github_repos 2/4 · googlelocal 1/4 · music_brainz_20k 1/3 · agnews 0/4 · deps_dev_v1 0/2 · patents 0/3 |
| never passed by anyone upstream either | agnews/3, pancancer_atlas/1, patents/1 |

Both runs are on the central MLflow (`dataagentbench/evals`) with one trace per
trial, and in the explorer under **Runs**. The next step in the plan — v0 at
54 × 5 (≈ $45, most of one Max 5× window) — waits for review.

## 4 · The pages

- **Overview** — the numbers above with their denominators, the datasets
  hardest-first, the validator styles, the leaderboard's spread.
- **Datasets / Dataset** — engines, database files with sizes, the schema
  description the agent reads, the hint file as a toggle, the queries.
- **Queries** — all 54, filterable by dataset, validator style and gold shape,
  sortable by published pass rate.
- **Query** — question, gold and `validate.py` side by side; then every
  answer file's trials with passing and failing answers verbatim and the
  validator's own reason on each failure.
- **Validators** — the four styles (33 regex/number, 12 substring/list,
  9 levenshtein, 0 read the CSV) and which queries use each.
- **Leaderboard** — the site's 40 entries, the nine with committed answers
  marked, and the stratified tables with our rescore beside them.
- **Runs / Run / Trace** — our own evals from `runs/`: the champion and every
  challenger measured against it, the per-trial profile (mean / p50 / p95 of
  turns, tokens, wall, cost), every trial with its tokens and cost, and the
  full trace as a span waterfall plus the transcript, each linked to (and,
  for a trace, embedding) its MLflow run and trace.
- **Agent** — the agent system as a graph generated from `agents/<name>/`
  and the tool server's own schemas; click a node for its config, a tool for a
  form that runs it with the trial's guards (read-only role, network-off
  sandbox, never a model); pick a trace to overlay call counts and replay it
  turn by turn, re-running any tool call with a changed input.

## 5 · Attribution

Everything under `data/index/` and `data/answers/` is derived from
`ucbepic/DataAgentBench` at the commit named in `data/index/source.json`; see
`data/index/ATTRIBUTION.md`. The upstream repository publishes no licence file;
the copy exists so the explorer runs from a bare clone and is removed on
request. This project's own code is MIT.

Design brief: `DESIGN.md`. Decisions and layout: `AGENTS.md`. The plans the
builds were approved against: `.lavish/s00_dab-explorer-init-plan.html`
(explorer), `.lavish/s01_agent-blueprint.html` (agent) and
`.lavish/s02_agent-tab.html` (the Agent tab).
