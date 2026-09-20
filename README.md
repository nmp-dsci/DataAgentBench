# DataAgentBench explorer

An explorer over the [DAB](https://github.com/ucbepic/DataAgentBench)
benchmark (DataAgentBench, UC Berkeley EPIC + Hasura PromptQL,
[arXiv 2603.20576](https://arxiv.org/abs/2603.20576)): its datasets,
questions, gold answers, validators and the published trials, ingested from
the upstream repo into a committed index and served as a small app. Nothing
here calls a model; the agent, the evals and the loop are later builds on this
skeleton.

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

## 5 · Attribution

Everything under `data/index/` and `data/answers/` is derived from
`ucbepic/DataAgentBench` at the commit named in `data/index/source.json`; see
`data/index/ATTRIBUTION.md`. The upstream repository publishes no licence file;
the copy exists so the explorer runs from a bare clone and is removed on
request. This project's own code is MIT.

Design brief: `DESIGN.md`. Decisions and layout: `AGENTS.md`. The plan this
build was approved against: `.lavish/s00_dab-explorer-init-plan.html`.
