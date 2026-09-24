"""What the model receives: one fixed behaviour file plus one dataset's facts, then the question.

Decision D7 A (plan s01): the dataset's facts go in the *system* prompt —
`system.md` (identical for every trial) followed by the code-built tables map,
the curated `summary.md` and `pitfalls.md` (when the version's `pack` is on),
the version's own notes for the dataset (written by the optimiser, s06), the
upstream description and, when the run asks for it, the upstream hints; the
description and the hints verbatim. The user message is the question alone, as
the benchmark poses it. `context_sha` pins which pack bytes a trial saw.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dab_bench.config import CONTEXT_DIR

PACK_FILES = ("summary.md", "pitfalls.md", "description.txt", "hints.txt", "tables.json")


@dataclass(frozen=True)
class DatasetContext:
    dataset: str
    path: Path
    summary: str
    pitfalls: str
    description: str
    hints: str
    tables: list[dict[str, Any]]
    context_sha: str


def load_context(dataset: str, context_dir: Path = CONTEXT_DIR) -> DatasetContext:
    d = context_dir / dataset
    if not (d / "tables.json").exists():
        raise FileNotFoundError(f"no context pack at {d} (run `dab context build`)")

    def read(name: str) -> str:
        p = d / name
        return p.read_text() if p.exists() else ""

    h = hashlib.sha256()
    for name in PACK_FILES:
        h.update(name.encode())
        h.update(read(name).encode())
    return DatasetContext(
        dataset=dataset,
        path=d,
        summary=read("summary.md"),
        pitfalls=read("pitfalls.md"),
        description=read("description.txt"),
        hints=read("hints.txt"),
        tables=json.loads(read("tables.json") or "[]"),
        context_sha=h.hexdigest()[:12],
    )


def tables_block(ctx: DatasetContext) -> str:
    lines = []
    for t in ctx.tables:
        columns = t.get("columns") or []
        cols = ", ".join(str(c.get("name")) for c in columns if isinstance(c, dict))
        rows = t.get("rows")
        n = f"{int(rows):,}" if isinstance(rows, int) else "?"
        lines.append(f"- `{t.get('table')}` ({n} rows; store {t.get('store')}): {cols}")
    return "\n".join(lines)


def compose_system_prompt(
    system_md: str, ctx: DatasetContext, hints: bool, pack: bool = True, notes: str = ""
) -> str:
    parts = [
        system_md.rstrip(),
        f"\n\n# Dataset: {ctx.dataset}\n",
        "All tables live in one Postgres schema, `dataagentbench`, named `<dataset>_<table>`; "
        "`query_db` runs read-only SQL against it.\n",
        "## Tables\n" + tables_block(ctx),
    ]
    if pack and ctx.summary.strip():
        parts.append("\n## Summary (curated from the data)\n" + ctx.summary.strip())
    if pack and ctx.pitfalls.strip():
        parts.append("\n## Pitfalls in the data\n" + ctx.pitfalls.strip())
    if notes.strip():
        parts.append("\n## Notes for this dataset\n" + notes.strip())
    if ctx.description.strip():
        parts.append("\n## Database description (upstream, verbatim)\n" + ctx.description.strip())
    if hints and ctx.hints.strip():
        parts.append("\n## Hints (upstream, verbatim)\n" + ctx.hints.strip())
    return "\n".join(parts) + "\n"


def user_message(question: str) -> str:
    return question.strip()
