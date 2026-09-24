"""`make rescore`: every committed answer, judged by its query's validator, summarised per query and per file.

Work is split into (query, answer file) tasks over a process pool, so the nine
slow levenshtein queries do not serialise the run. Per-row verdicts go to
`data/index/verdicts.jsonl` (gitignored, large); the per-query summary with a
few example rows goes to `data/index/trials.json` (committed, what the API
reads). Two averages are reported per file because the site's Pass@1 is the
macro one: the mean over datasets of each dataset's mean per-query pass rate.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dab_bench.config import TRIALS_PATH, VERDICTS_PATH
from dab_bench.data.index import Index, load
from dab_bench.data.upstream import require
from dab_bench.eval.validators import judge, load_validator, query_dir

EXAMPLES = 3


def _task(
    args: tuple[str, str, str, int, list[tuple[int, str]], int],
) -> tuple[str, str, list[dict[str, Any]]]:
    """Worker: judge every (row index, answer) of one query from one file. Runs in its own process."""
    qid, root, folder, query_id, rows, timeout_s = args
    fn = load_validator(query_dir(Path(root), folder, query_id), Path(root))
    out = []
    for i, answer in rows:
        v = judge(fn, answer, timeout_s)
        out.append(
            {"i": i, "ok": v.ok, "reason": v.reason, "timed_out": v.timed_out, "error": v.error}
        )
    return qid, "", out


def run(
    workers: int = 4, timeout_s: int = 30, limit: int | None = None, ix: Index | None = None
) -> dict[str, Any]:
    up = require()
    ix = ix or load(fresh=True)
    started = time.time()

    tasks: list[tuple[str, str, str, int, list[tuple[int, str]], int]] = []
    file_of_task: list[str] = []
    for q in ix.queries[:limit] if limit else ix.queries:
        folder = ix.dataset_by_key[q["dataset_key"]]["folder"]
        for fname, rows in ix.answers.get(q["id"], {}).items():
            tasks.append(
                (
                    q["id"],
                    str(up.path),
                    folder,
                    q["query_id"],
                    [(r["i"], r["answer"]) for r in rows],
                    timeout_s,
                )
            )
            file_of_task.append(fname)

    verdicts: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(dict)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_task, t): file_of_task[k] for k, t in enumerate(tasks)}
        for fut in as_completed(futures):
            qid, _, rows = fut.result()
            verdicts[qid][futures[fut]] = rows

    trials = summarise(ix, verdicts, up.commit, time.time() - started, timeout_s)
    TRIALS_PATH.write_text(json.dumps(trials, ensure_ascii=False, indent=1) + "\n")
    with VERDICTS_PATH.open("w") as f:
        for qid, by_file in sorted(verdicts.items()):
            for fname, rows in sorted(by_file.items()):
                for r in rows:
                    f.write(json.dumps({"id": qid, "file": fname, **r}, ensure_ascii=False) + "\n")
    summary: dict[str, Any] = trials["summary"]
    return summary


def summarise(
    ix: Index,
    verdicts: dict[str, dict[str, list[dict[str, Any]]]],
    commit: str,
    seconds: float,
    timeout_s: int,
) -> dict[str, Any]:
    # A reference file (`pooled: False`, a leaderboard entry read from its PR) is judged and
    # kept per file, but each query's pooled n / passed / rate stays the public baselines'.
    reference = {
        f["name"] for f in ix.leaderboard.get("answer_files", []) if not f.get("pooled", True)
    }
    per_query: dict[str, Any] = {}
    for qid, by_file in verdicts.items():
        files: dict[str, Any] = {}
        for fname, rows in by_file.items():
            passes = [r["i"] for r in rows if r["ok"]]
            fails = [{"i": r["i"], "reason": r["reason"][:400]} for r in rows if not r["ok"]]
            files[fname] = {
                "n": len(rows),
                "passed": len(passes),
                "timed_out": sum(1 for r in rows if r["timed_out"]),
                "errors": sum(1 for r in rows if r["error"]),
                "pass_examples": passes[:EXAMPLES],
                "fail_examples": fails[:EXAMPLES],
            }
        pooled = [f for name, f in files.items() if name not in reference]
        n = sum(f["n"] for f in pooled)
        passed = sum(f["passed"] for f in pooled)
        per_query[qid] = {
            "n": n,
            "passed": passed,
            "rate": passed / n if n else None,
            "timed_out": sum(f["timed_out"] for f in pooled),
            "files": dict(sorted(files.items())),
        }

    # Per file: micro (rows) and macro (mean over datasets of mean per-query rate), plus per dataset.
    per_file: dict[str, Any] = {}
    file_names = sorted({f for q in verdicts.values() for f in q})
    for fname in file_names:
        by_ds: dict[str, list[float]] = defaultdict(list)
        n_rows = passed = 0
        for qid, t in per_query.items():
            f = t["files"].get(fname)
            if not f or not f["n"]:
                continue
            by_ds[qid.split("/")[0]].append(f["passed"] / f["n"])
            n_rows += f["n"]
            passed += f["passed"]
        per_dataset = {ds: sum(r) / len(r) for ds, r in sorted(by_ds.items())}
        per_file[fname] = {
            "rows": n_rows,
            "passed": passed,
            "micro": passed / n_rows if n_rows else None,
            "macro": sum(per_dataset.values()) / len(per_dataset) if per_dataset else None,
            "per_dataset": per_dataset,
        }

    site_check = _site_check(ix, per_file)
    rates = [(t["rate"], qid) for qid, t in per_query.items() if t["n"]]
    summary = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": commit,
        "seconds": round(seconds, 1),
        "timeout_s": timeout_s,
        "rows": sum(t["n"] for t in per_query.values()),
        "queries": len(per_query),
        "files": len(per_file),
        "timed_out": sum(t["timed_out"] for t in per_query.values()),
        "never_passed": sorted(qid for r, qid in rates if r == 0),
        "under_10pct": sorted(qid for r, qid in rates if r is not None and r < 0.10),
        "at_least_95pct": sorted(qid for r, qid in rates if r is not None and r >= 0.95),
        "site_check_max_abs_diff": site_check["max_abs_diff"],
    }
    return {
        "summary": summary,
        "per_file": per_file,
        "per_query": dict(sorted(per_query.items())),
        "site_check": site_check,
    }


def _site_check(ix: Index, per_file: dict[str, Any]) -> dict[str, Any]:
    """Our macro per-dataset numbers next to the site's stratified tables, for the files that have a column."""
    lb = ix.leaderboard
    meta = {f["name"]: f for f in lb.get("answer_files", [])}
    out: dict[str, Any] = {"files": {}, "overall": {}, "max_abs_diff": 0.0}
    for fname, pf in per_file.items():
        site_p1 = (meta.get(fname) or {}).get("pass_at_1_site")
        if site_p1 is not None and pf["macro"] is not None:
            out["overall"][fname] = {
                "ours": round(pf["macro"], 4),
                "site": site_p1,
                "diff": round(pf["macro"] - site_p1, 4),
            }
        strat = (meta.get(fname) or {}).get("stratified")
        if not strat:
            continue
        table, col = strat.split(":")
        rows = lb.get(table, {}).get("rows", [])
        scale = 100.0 if table == "promptqlStratified" else 1.0
        cmp: dict[str, Any] = {}
        for row in rows:
            ds = _ds_key(row["dataset"])
            site = row.get(col)
            ours = pf["per_dataset"].get(ds)
            if site is None or ours is None:
                continue
            site_f = float(site) / scale
            cmp[ds] = {
                "ours": round(ours, 4),
                "site": round(site_f, 4),
                "diff": round(ours - site_f, 4),
            }
            out["max_abs_diff"] = max(out["max_abs_diff"], abs(ours - site_f))
        overall = lb.get(table, {}).get("overall", {}).get(col)
        out["files"][fname] = {
            "table": table,
            "column": col,
            "per_dataset": cmp,
            "overall_site": (float(overall) / scale) if overall is not None else None,
            "overall_ours_macro": pf["macro"],
        }
    out["max_abs_diff"] = round(out["max_abs_diff"], 4)
    return out


def _ds_key(name: str) -> str:
    from dab_bench.data.aliases import dataset_key

    return dataset_key(name)
