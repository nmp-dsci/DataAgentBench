"""Names, and the one key that joins them.

Upstream spells a dataset three ways: the folder (`query_DEPS_DEV_V1`), the site
(`deps_dev_v1`) and the answer files (`deps_dev` in the PromptQL runs,
`DEPS_DEV_V1` in the ReAct baselines). The canonical `dataset_key` is the folder
name without `query_`, lower-cased; `DATASET_ALIASES` is the site's own map from
`docs/app.js`, applied on top.
"""

from __future__ import annotations

from typing import Any

FOLDER_PREFIX = "query_"

# From docs/app.js `DATASET_ALIASES`, verbatim.
DATASET_ALIASES: dict[str, str] = {
    "deps_dev": "deps_dev_v1",
    "music_brainz": "music_brainz_20k",
    "pancancer": "pancancer_atlas",
}

# The 12 datasets the README, the site and the submission rubric describe: the
# leaderboard set. Decided in review (s00, decision B): this build's index is
# these and nothing else; the others are recorded as a count.
RELEASED_DATASETS: frozenset[str] = frozenset(
    {
        "agnews",
        "bookreview",
        "crmarenapro",
        "deps_dev_v1",
        "github_repos",
        "googlelocal",
        "music_brainz_20k",
        "pancancer_atlas",
        "patents",
        "stockindex",
        "stockmarket",
        "yelp",
    }
)


def dataset_key(name: str) -> str:
    """Canonical key for a folder name, a site key or an answer-file spelling."""
    n = name.strip()
    n = n.removeprefix(FOLDER_PREFIX)
    n = n.lower()
    return DATASET_ALIASES.get(n, n)


def query_key(dataset: str, query: str | int) -> str:
    """`crmarenapro/1` — the id every index file and every answer row joins on."""
    q = str(query).strip()
    q = q.removeprefix("query")
    return f"{dataset_key(dataset)}/{int(q)}"


# The answer files committed upstream, and the leaderboard row each one is.
# `agent` is matched exactly against `overallLeaderboard[].agent` in the site's
# leaderboards.json; `stratified` names the table and column that carry the
# same run's per-dataset numbers. A file with no row (PromptQL + GPT-5.2) is
# still rescored and shown; it simply has no rank.
#
# The leaderboard's top entries never reached main: their answers sit on the
# submission PR's branch (the site scores them from there). Those carry `pr` and
# `commit`, the PR head they are pinned to; `make upstream` fetches that commit
# into the clone and the ingest reads the file from it with `git show`, so the
# checkout stays at the ingested commit. `pooled: False` makes a file a
# reference: rescored and shown per query and per file, and comparable on the
# Runs tab, but left out of each query's pooled published rate, which stays the
# public baselines' number.
ANSWER_FILES: dict[str, dict[str, Any]] = {
    "submissions/react_gpt-5.2.json": {
        "label": "GPT-5.2 ReAct",
        "agent": "GPT-5.2 ReAct",
        "stratified": "baselineStratified:gpt52",
    },
    "submissions/react_gpt-5-mini.json": {
        "label": "GPT-5-mini ReAct",
        "agent": "GPT-5-mini ReAct",
        "stratified": "baselineStratified:gpt5mini",
    },
    "submissions/react_gemini-3-pro.json": {
        "label": "Gemini-3-Pro ReAct",
        "agent": "Gemini-3-Pro ReAct",
        "stratified": "baselineStratified:gemini3pro",
    },
    "submissions/react_gemini-2.5-flash.json": {
        "label": "Gemini-2.5-Flash ReAct",
        "agent": "Gemini-2.5-Flash ReAct",
        "stratified": "baselineStratified:gemini25flash",
    },
    "submissions/react_kimi-k2-thinking.json": {
        "label": "Kimi-K2 ReAct",
        "agent": "Kimi-K2 ReAct",
        "stratified": "baselineStratified:kimik2",
    },
    "submissions/promptql_opus46_wiki4_pp2_n5.json": {
        "label": "PromptQL + Claude Opus 4.6",
        "agent": "PromptQL + Claude Opus 4.6",
        "stratified": "promptqlStratified:opus46",
    },
    "submissions/promptql_gemini31pro_wiki4_pp2_n5.json": {
        "label": "PromptQL + Gemini 3.1 Pro",
        "agent": "PromptQL + Gemini 3.1 Pro",
        "stratified": "promptqlStratified:gemini31pro",
    },
    "submissions/promptql_gpt52_wiki4_pp2_n5.json": {
        "label": "PromptQL + GPT-5.2",
        "agent": None,
        "stratified": "promptqlStratified:gpt52",
    },
    "leaderboard_submissions/claude-opus-4-6_results.json": {
        "label": "Claude Opus 4.6 ReAct",
        "agent": "Claude Opus 4.6 ReAct",
        "stratified": None,
    },
    # Leaderboard #1 and #2 as of 2026-09-15.
    "leaderboard_submissions/permute_eq.json": {
        "label": "Permute EQ (Claude Opus 5)",
        "agent": "Permute EQ (Claude Opus 5)",
        "stratified": None,
        "pr": 95,
        "commit": "02918bb09f4c2e92bc5f1918973b96b896041a6d",
        "pooled": False,
    },
    "leaderboard_submissions/oceanbase_lab_scout.json": {
        "label": "Scout (OceanBase Lab) (GLM-5.2)",
        "agent": "Scout (OceanBase Lab) (GLM-5.2)",
        "stratified": None,
        "pr": 96,
        "commit": "be589390f4a1a8d75304ccbdb5a34fa196cbb2ca",
        "pooled": False,
    },
}


def pinned_commits() -> list[str]:
    """The PR heads the reference answer files are read from, for `make upstream` to fetch."""
    return sorted({str(m["commit"]) for m in ANSWER_FILES.values() if m.get("commit")})


def answer_file_name(upstream_path: str) -> str:
    """`submissions/react_gpt-5.2.json` → `react_gpt-5.2` — the name used in data/answers and trials.json."""
    return upstream_path.rsplit("/", 1)[-1].removesuffix(".json").removesuffix("_results")
