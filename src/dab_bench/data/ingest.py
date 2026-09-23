"""`make ingest`: walk the upstream clone and write `data/index/`.

Deterministic and offline: the same commit in gives the same files out. The
index is committed, so the API, the explorer, CI and the tests never need the
clone. Only `rescore` does (it imports each query's `validate.py`).

What is in scope is decided by `aliases.RELEASED_DATASETS` (the 12 leaderboard
datasets, 54 queries). The other datasets upstream are counted in
`source.json` and nothing else about them is written.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from dab_bench.config import (
    ANSWERS_DIR,
    ATTRIBUTION_PATH,
    DATASETS_PATH,
    INDEX_DIR,
    LEADERBOARD_PATH,
    MANIFEST_PATH,
    QUERIES_PATH,
    SOURCE_PATH,
    UPSTREAM_PAPER,
    UPSTREAM_REPO,
    VALIDATORS_PATH,
)
from dab_bench.data.aliases import (
    ANSWER_FILES,
    FOLDER_PREFIX,
    RELEASED_DATASETS,
    answer_file_name,
    dataset_key,
    query_key,
)
from dab_bench.data.upstream import Upstream, is_lfs_pointer, require, show

VALIDATOR_STYLES = ("regex", "reads-gold-file", "substring", "levenshtein")


def classify_validator(source: str) -> str:
    """Four styles, by what the source does — the same rule the plan's tables were counted with."""
    if "levenshtein" in source:
        return "levenshtein"
    if "ground_truth.csv" in source:
        return "reads-gold-file"
    if "import re" in source:
        return "regex"
    return "substring"


@dataclass
class IngestResult:
    commit: str
    datasets_total: int
    queries_total: int
    datasets_in_scope: int
    queries_in_scope: int
    deferred_datasets: list[str]
    deferred_queries: int
    answer_rows: int
    answer_rows_unmatched: int
    warnings: list[str] = field(default_factory=list)


def _read_manifest(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in (root / "dataset_manifest.tsv").read_text().splitlines():
        if not line.strip():
            continue
        path, sha256, size = line.split("\t")
        key = dataset_key(path.split("/", 1)[0])
        out.append(
            {
                "path": path,
                "sha256": sha256,
                "bytes": int(size),
                "dataset_key": key,
                "in_scope": key in RELEASED_DATASETS,
                "is_lfs_pointer": is_lfs_pointer(root / path),
            }
        )
    return out


def _on_disk_bytes(path: Path) -> int | None:
    """Size of a file or folder that is in git directly (not in the manifest), pointers excluded."""
    if path.is_file():
        return None if is_lfs_pointer(path) else path.stat().st_size
    if path.is_dir():
        files = [f for f in path.rglob("*") if f.is_file() and not is_lfs_pointer(f)]
        return sum(f.stat().st_size for f in files) if files else None
    return None


def _dataset_folders(root: Path) -> list[Path]:
    return sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith(FOLDER_PREFIX))


def _query_dirs(folder: Path) -> list[Path]:
    dirs = [
        p
        for p in folder.iterdir()
        if p.is_dir() and p.name.startswith("query") and p.name[5:].isdigit()
    ]
    return sorted(dirs, key=lambda p: int(p.name[5:]))


def _read_dataset(folder: Path, manifest: list[dict[str, Any]]) -> dict[str, Any]:
    key = dataset_key(folder.name)
    cfg = yaml.safe_load((folder / "db_config.yaml").read_text()) or {}
    by_path = {m["path"]: m for m in manifest}
    dbs: list[dict[str, Any]] = []
    for name, client in (cfg.get("db_clients") or {}).items():
        client = dict(client)
        file_rel = (
            client.get("db_path")
            or client.get("sql_file")
            or client.get("dump_folder")
            or client.get("dump_dir")
        )
        entry: dict[str, Any] = {"name": name, "engine": client.get("db_type"), "config": client}
        if file_rel:
            m = by_path.get(f"{folder.name}/{file_rel}")
            entry["file"] = file_rel
            entry["in_manifest"] = m is not None
            entry["bytes"] = m["bytes"] if m else _on_disk_bytes(folder / file_rel)
            entry["sha256"] = m["sha256"] if m else None
        dbs.append(entry)
    description = (folder / "db_description.txt").read_text()
    hints_path = folder / "db_description_withhint.txt"
    hints = hints_path.read_text() if hints_path.exists() else ""
    engines = sorted({d["engine"] for d in dbs if d.get("engine")})
    queries = [query_key(key, q.name) for q in _query_dirs(folder)]
    return {
        "key": key,
        "folder": folder.name,
        "released": key in RELEASED_DATASETS,
        "n_queries": len(queries),
        "queries": queries,
        "engines": engines,
        "n_dbs": len(dbs),
        "dbs": dbs,
        "bytes_total": sum(m["bytes"] for m in manifest if m["dataset_key"] == key)
        + sum(d.get("bytes") or 0 for d in dbs if not d.get("in_manifest", True)),
        "description": description,
        "description_bytes": len(description.encode()),
        "hints": hints,
        "hints_bytes": len(hints.encode()),
    }


def _read_query(
    folder: Path, qdir: Path, footnotes: dict[str, str], site_text: dict[str, str]
) -> dict[str, Any]:
    key = dataset_key(folder.name)
    qid = int(qdir.name[5:])
    qkey = query_key(key, qid)
    question_raw = (qdir / "query.json").read_text()
    try:
        question = json.loads(question_raw)
        if not isinstance(question, str):
            question = question_raw.strip()
    except json.JSONDecodeError:
        question = question_raw.strip()
    gold = (qdir / "ground_truth.csv").read_text()
    gold_text = gold.strip("\n")
    source = (qdir / "validate.py").read_text()
    style = classify_validator(source)
    site = site_text.get(qkey)
    return {
        "id": qkey,
        "dataset_key": key,
        "query_id": qid,
        "question": question,
        "gold_text": gold_text,
        "gold_lines": len([ln for ln in gold_text.splitlines() if ln.strip()]),
        "validator": {
            "style": style,
            "lines": len(source.splitlines()),
            "reads_gold_file": style == "reads-gold-file",
            "source": source,
        },
        "released": key in RELEASED_DATASETS,
        "on_site": site is not None,
        "site_text_matches": (site.strip() == question.strip()) if site is not None else None,
        "footnote": footnotes.get(qkey),
    }


def _footnotes(leaderboard: dict[str, Any], queries: list[str]) -> dict[str, str]:
    """Map the site's `sources[]` notes to the queries they name, by the text itself."""
    out: dict[str, str] = {}
    for note in leaderboard.get("sources") or []:
        if "DEPS_DEV_V1 query 1" in note:
            out["deps_dev_v1/1"] = note
        if "PATENTS" in note:
            for q in queries:
                if q.startswith("patents/"):
                    out[q] = note
    return out


def _leaderboard(root: Path) -> dict[str, Any]:
    path = root / "docs" / "data" / "leaderboards.json"
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def _site_queries(root: Path) -> dict[str, str]:
    path = root / "docs" / "data" / "queries.json"
    if not path.exists():
        return {}
    return {
        query_key(q["dataset"], q["queryId"]): str(q["text"]) for q in json.loads(path.read_text())
    }


def _copy_answers(
    root: Path, in_scope: set[str], leaderboard: dict[str, Any], warnings: list[str]
) -> tuple[list[dict[str, Any]], int, int]:
    """Normalise each committed answer file into data/answers/<name>.json and describe it."""
    ANSWERS_DIR.mkdir(parents=True, exist_ok=True)
    for old in ANSWERS_DIR.glob("*.json"):
        old.unlink()
    rank_by_agent = {row["agent"]: row for row in leaderboard.get("overallLeaderboard") or []}
    files: list[dict[str, Any]] = []
    total = 0
    unmatched_total = 0
    for upstream_path, meta in ANSWER_FILES.items():
        if meta.get("commit"):
            if not (root / ".git").exists():
                continue  # an unpacked tree (the test fixture) carries no PR objects
            text = show(str(meta["commit"]), upstream_path, root)
            if text is None:
                warnings.append(
                    f"{upstream_path} skipped: pinned to PR #{meta['pr']} at {meta['commit']}, "
                    "which the clone has not fetched; run `make upstream`"
                )
                continue
        else:
            src = root / upstream_path
            if not src.exists():
                continue
            text = src.read_text()
        rows = json.loads(text)
        name = answer_file_name(upstream_path)
        norm: list[dict[str, Any]] = []
        unmatched = 0
        per_query: Counter[str] = Counter()
        for r in rows:
            qkey = query_key(str(r["dataset"]), r["query"])
            if qkey not in in_scope:
                unmatched += 1
                continue
            norm.append(
                {
                    "id": qkey,
                    "run": int(r["run"]),
                    "answer": "" if r.get("answer") is None else str(r["answer"]),
                }
            )
            per_query[qkey] += 1
        (ANSWERS_DIR / f"{name}.json").write_text(
            json.dumps(norm, ensure_ascii=False, indent=0) + "\n"
        )
        row = rank_by_agent.get(meta["agent"] or "")
        files.append(
            {
                "name": name,
                "upstream_path": upstream_path,
                "label": meta["label"],
                "agent": meta["agent"],
                "rank": row["rank"] if row else None,
                "pass_at_1_site": row["passAt1"] if row else None,
                "stratified": meta["stratified"],
                "pooled": bool(meta.get("pooled", True)),
                "pr": meta.get("pr"),
                "pr_url": f"{UPSTREAM_REPO.removesuffix('.git')}/pull/{meta['pr']}"
                if meta.get("pr")
                else None,
                "commit": meta.get("commit"),
                "rows": len(norm),
                "rows_unmatched": unmatched,
                "queries": len(per_query),
                "runs_per_query": sorted(set(per_query.values())),
            }
        )
        total += len(norm)
        unmatched_total += unmatched
    return files, total, unmatched_total


def _attribution(up: Upstream, when: str, counts: IngestResult) -> str:
    return f"""# Attribution

Everything under `data/index/` and `data/answers/` is derived from the DAB
benchmark (DataAgentBench), a collaboration between UC Berkeley's EPIC Data Lab
and Hasura PromptQL:

- Repository: {up.repo} at commit `{up.commit}`
- Paper: Ma, Shankar, Chen, Lin, Zeighami, Ghosh, Gupta, Gupta, Gopal and
  Parameswaran, *Can AI Agents Answer Your Data Questions? A Benchmark for
  Data Agents*, 2026. {UPSTREAM_PAPER}
- Ingested: {when} by `dab ingest`

The index carries the question text, the ground-truth answers, the validator
source and the dataset descriptions of the {counts.queries_in_scope} leaderboard
queries across {counts.datasets_in_scope} datasets, and normalised copies of the
{counts.answer_rows} published answers, committed upstream or on a leaderboard
submission's PR branch (pinned by commit in `leaderboard.json`). No database file
is copied. The upstream repository publishes no licence file; this copy exists so
the explorer runs from a bare clone, and it is removed on request.
"""


def run(root: Path | None = None, commit: str | None = None) -> IngestResult:
    """Ingest the clone at `root` (default data/upstream). `commit` skips the git lookup, for fixture trees."""
    if root is not None and commit is not None:
        up = Upstream(path=root, commit=commit, repo=UPSTREAM_REPO)
    else:
        up = require(root) if root else require()
    root = up.path
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    manifest = _read_manifest(root)
    leaderboard = _leaderboard(root)
    site_text = _site_queries(root)

    folders = _dataset_folders(root)
    all_datasets = [_read_dataset(f, manifest) for f in folders]
    datasets = [d for d in all_datasets if d["released"]]
    deferred = [d for d in all_datasets if not d["released"]]
    in_scope_ids = [q for d in datasets for q in d["queries"]]
    footnotes = _footnotes(leaderboard, in_scope_ids)

    queries: list[dict[str, Any]] = []
    for folder in folders:
        if dataset_key(folder.name) not in RELEASED_DATASETS:
            continue
        for qdir in _query_dirs(folder):
            queries.append(_read_query(folder, qdir, footnotes, site_text))

    site_ids = set(site_text)
    ours = {q["id"] for q in queries}
    if site_ids and site_ids != ours:
        warnings.append(
            f"site queries.json differs from the released set: only-site={sorted(site_ids - ours)} only-here={sorted(ours - site_ids)}"
        )
    for q in queries:
        if q["site_text_matches"] is False:
            warnings.append(f"{q['id']}: question text differs from docs/data/queries.json")

    styles: dict[str, list[str]] = {s: [] for s in VALIDATOR_STYLES}
    for q in queries:
        styles[q["validator"]["style"]].append(q["id"])
    validators = {
        "styles": [
            {
                "style": s,
                "n": len(ids),
                "ids": ids,
                "longest": max(
                    (q["validator"]["lines"] for q in queries if q["validator"]["style"] == s),
                    default=0,
                ),
            }
            for s, ids in styles.items()
        ],
        "reads_gold_file": [q["id"] for q in queries if q["validator"]["reads_gold_file"]],
        "total_lines": sum(q["validator"]["lines"] for q in queries),
    }

    answer_files, answer_rows, unmatched = _copy_answers(root, ours, leaderboard, warnings)
    leaderboard_out = {**leaderboard, "answer_files": answer_files}

    when = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = IngestResult(
        commit=up.commit,
        datasets_total=len(all_datasets),
        queries_total=sum(d["n_queries"] for d in all_datasets),
        datasets_in_scope=len(datasets),
        queries_in_scope=len(queries),
        deferred_datasets=[d["key"] for d in deferred],
        deferred_queries=sum(d["n_queries"] for d in deferred),
        answer_rows=answer_rows,
        answer_rows_unmatched=unmatched,
        warnings=warnings,
    )
    source = {
        "repo": up.repo,
        "commit": up.commit,
        "paper": UPSTREAM_PAPER,
        "ingested_at": when,
        "datasets_total": result.datasets_total,
        "queries_total": result.queries_total,
        "in_scope": {"datasets": result.datasets_in_scope, "queries": result.queries_in_scope},
        "deferred": {"datasets": result.deferred_datasets, "queries": result.deferred_queries},
        "answer_rows": answer_rows,
        "answer_rows_unmatched": unmatched,
        "warnings": warnings,
    }

    _write(SOURCE_PATH, source)
    _write(DATASETS_PATH, datasets)
    _write(QUERIES_PATH, queries)
    _write(VALIDATORS_PATH, validators)
    _write(MANIFEST_PATH, manifest)
    _write(LEADERBOARD_PATH, leaderboard_out)
    ATTRIBUTION_PATH.write_text(_attribution(up, when, result))
    return result


def _write(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")


def clean() -> None:
    for p in (
        SOURCE_PATH,
        DATASETS_PATH,
        QUERIES_PATH,
        VALIDATORS_PATH,
        MANIFEST_PATH,
        LEADERBOARD_PATH,
        ATTRIBUTION_PATH,
    ):
        p.unlink(missing_ok=True)
    if ANSWERS_DIR.exists():
        shutil.rmtree(ANSWERS_DIR)
