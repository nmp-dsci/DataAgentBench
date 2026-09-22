"""Splits are committed lists of query ids under `data/splits/<name>.json`.

`smoke` is one query per dataset — decision D0 B: the median-difficulty query
by published pass rate (upper median where the count is even). `all` is every
query in the index (the 54). A split is a file so every run of it is the same
set and comparable over time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from dab_bench.config import QUERIES_PATH, SPLITS_DIR


@dataclass(frozen=True)
class Query:
    id: str
    dataset: str
    query_id: int
    question: str
    folder: str


def all_queries() -> list[Query]:
    from dab_bench.config import DATASETS_PATH

    folders = {d["key"]: d["folder"] for d in json.loads(DATASETS_PATH.read_text())}
    out = []
    for q in json.loads(QUERIES_PATH.read_text()):
        if not q.get("released", True):
            continue
        out.append(
            Query(
                id=q["id"],
                dataset=q["dataset_key"],
                query_id=int(q["query_id"]),
                question=q["question"],
                folder=folders[q["dataset_key"]],
            )
        )
    return out


def load_split(name: str) -> list[Query]:
    qs = {q.id: q for q in all_queries()}
    if name == "all":
        return list(qs.values())
    path = SPLITS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"no split {name} at {path}")
    ids = json.loads(path.read_text())["queries"]
    missing = [i for i in ids if i not in qs]
    if missing:
        raise KeyError(f"split {name} names queries not in the index: {missing}")
    return [qs[i] for i in ids]
