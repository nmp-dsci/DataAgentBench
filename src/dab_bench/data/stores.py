"""The benchmark's stores, as the index records them, and where each one lands in Postgres.

Every store of every released dataset becomes tables in one schema
(`dataagentbench`), named `<dataset>_<table>` — decision D6 A of the agent plan
(s01). This module is the naming rule and the file map; `load.py` moves bytes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from dab_bench.config import DATASETS_PATH, PG_SCHEMA, UPSTREAM_DIR

Engine = str  # "sqlite" | "duckdb" | "postgres" | "mongo"


@dataclass(frozen=True)
class Store:
    dataset: str
    folder: str
    name: str  # the db_config.yaml client name, e.g. `package_database`
    engine: Engine
    file: str | None  # relative to the dataset folder (sqlite/duckdb/postgres)
    dump_folder: str | None  # mongo only
    db_name: str | None
    bytes: int | None
    sha256: str | None
    in_manifest: bool

    @property
    def path(self) -> Path:
        rel = self.file or self.dump_folder or ""
        return UPSTREAM_DIR / self.folder / rel

    @property
    def dataset_folder(self) -> Path:
        return UPSTREAM_DIR / self.folder


def load_stores(datasets_path: Path = DATASETS_PATH) -> list[Store]:
    """Every store of every released dataset, from the committed index."""
    out: list[Store] = []
    for d in json.loads(datasets_path.read_text()):
        if not d.get("released", True):
            continue
        for db in d["dbs"]:
            cfg = db.get("config", {})
            out.append(
                Store(
                    dataset=d["key"],
                    folder=d["folder"],
                    name=db["name"],
                    engine=db["engine"],
                    file=db.get("file") or cfg.get("db_path") or cfg.get("sql_file"),
                    dump_folder=cfg.get("dump_folder"),
                    db_name=cfg.get("db_name"),
                    bytes=db.get("bytes"),
                    sha256=db.get("sha256"),
                    in_manifest=bool(db.get("in_manifest")),
                )
            )
    return out


def stores_for(dataset: str) -> list[Store]:
    return [s for s in load_stores() if s.dataset == dataset]


_IDENT = re.compile(r"[^a-z0-9_]+")


def pg_table(dataset: str, table: str) -> str:
    """`<dataset>_<table>`, lower-cased, non-identifier characters folded to `_`.

    The mapping must be injective per dataset; `load.py` fails loudly when two
    source tables in one dataset fold to the same name.
    """
    t = _IDENT.sub("_", table.strip().lower()).strip("_")
    return f"{dataset}_{t}"


def qualified(dataset: str, table: str) -> str:
    return f'{PG_SCHEMA}."{pg_table(dataset, table)}"'
