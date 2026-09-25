"""Agent versions are folders: `agents/<name>/{system.md, agent.yaml, helper.py, datasets/}`.

`system.md`, `helper.py` and the per-dataset notes `datasets/<ds>.md` are the surfaces
an optimiser edits; `agent.yaml` is frozen across a comparison so it is between prompts,
not budgets. The fingerprint (every surface plus agent.yaml) is what a run is logged
against. `agents/champion` is a one-line pointer file naming the current champion
version (`dab promote` moves it).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from dab_bench.agent.prompt import DatasetContext, compose_system_prompt
from dab_bench.config import AGENTS_DIR

SURFACES = ("system.md", "helper.py")
FROZEN = ("agent.yaml",)
CHAMPION_FILE = AGENTS_DIR / "champion"
NOT_EVAL_AGENTS = ("curator", "optimiser", "reader")  # agents that never answer a question


@dataclass(frozen=True)
class AgentConfig:
    model: str = "haiku"
    effort: str | None = None
    max_turns: int = 60
    timeout_s: int = 900
    exec_timeout_s: int = 600
    tools: list[str] = field(
        default_factory=lambda: [
            "mcp__dab__list_db",
            "mcp__dab__describe_table",
            "mcp__dab__sample_rows",
            "mcp__dab__query_db",
            "mcp__dab__execute_python",
            "mcp__dab__llm_extract",
            "mcp__dab__read_context",
            "mcp__dab__search_context",
            "mcp__dab__return_answer",
        ]
    )
    hints: bool = (
        False  # v0 runs without the upstream hint file; `--hints` is the reference's --use_hints
    )
    pack: bool = True  # the curated summary.md + pitfalls.md in the prompt (off for v1_sql, D26)
    challenger_of: str | None = None  # the version this one was optimised from
    # a hand-built version measured against another (v4_sql against v3_sql: a model switch, s08)
    measured_against: str | None = None
    # plan first (s08, D34): submit_answer requires `plan`, the statement's seven steps in words
    plan: bool = False


@dataclass(frozen=True)
class AgentVersion:
    name: str
    path: Path
    system_prompt: str
    config: AgentConfig
    helper: str | None
    fingerprint: str
    notes: dict[str, str] = field(default_factory=dict)  # dataset → datasets/<ds>.md

    @property
    def submits_sql(self) -> bool:
        """The SQL-answer contract (s06, D27): the trial ends with submit_answer(sql, …)."""
        return "mcp__dab__submit_answer" in self.config.tools

    @property
    def needs_sandbox(self) -> bool:
        return bool({"mcp__dab__execute_python", "mcp__dab__llm_extract"} & set(self.config.tools))

    def prompt_for(self, ctx: DatasetContext, hints: bool | None = None) -> str:
        """The system prompt a trial on `ctx`'s dataset receives."""
        return compose_system_prompt(
            self.system_prompt,
            ctx,
            hints=self.config.hints if hints is None else hints,
            pack=self.config.pack,
            notes=self.notes.get(ctx.dataset, ""),
        )

    @property
    def helper_path(self) -> Path | None:
        p = self.path / "helper.py"
        return p if p.exists() else None

    def files(self) -> dict[str, str]:
        out = {"system.md": self.system_prompt}
        if (self.path / "agent.yaml").exists():
            out["agent.yaml"] = (self.path / "agent.yaml").read_text()
        if self.helper is not None:
            out["helper.py"] = self.helper
        for ds, text in sorted(self.notes.items()):
            out[f"datasets/{ds}.md"] = text
        return out


def _surface_files(path: Path) -> list[tuple[str, Path]]:
    files = [(name, path / name) for name in sorted(SURFACES + FROZEN)]
    files += [(f"datasets/{p.name}", p) for p in sorted((path / "datasets").glob("*.md"))]
    return [(n, p) for n, p in files if p.exists()]


def fingerprint_dir(path: Path) -> str:
    h = hashlib.sha256()
    for name, p in _surface_files(path):
        h.update(name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def load_notes(path: Path) -> dict[str, str]:
    return {p.stem: p.read_text() for p in sorted((path / "datasets").glob("*.md"))}


def load_version(name: str) -> AgentVersion:
    if name == "champion":
        name = champion_name()
    path = AGENTS_DIR / name
    if not (path / "system.md").exists():
        raise FileNotFoundError(f"no agent at {path}")
    cfg_raw = (
        yaml.safe_load((path / "agent.yaml").read_text()) if (path / "agent.yaml").exists() else {}
    )
    config = AgentConfig(**(cfg_raw or {}))
    helper = (path / "helper.py").read_text() if (path / "helper.py").exists() else None
    return AgentVersion(
        name=name,
        path=path,
        system_prompt=(path / "system.md").read_text(),
        config=config,
        helper=helper,
        fingerprint=fingerprint_dir(path),
        notes=load_notes(path),
    )


def champion_name() -> str:
    return CHAMPION_FILE.read_text().strip() if CHAMPION_FILE.exists() else "v0"


def list_versions() -> list[str]:
    if not AGENTS_DIR.exists():
        return []
    return sorted(
        p.name
        for p in AGENTS_DIR.iterdir()
        if p.is_dir() and (p / "system.md").exists() and p.name not in NOT_EVAL_AGENTS
    )


def copy_with_model(src: str, into: str, model: str, agents_dir: Path = AGENTS_DIR) -> Path:
    """A hand-built version that differs from `src` only in its model (plan s08, D35 A): the same
    prompt files, `model` changed, `measured_against: src`, no `challenger_of` (it is not an
    optimisation round). Never overwrites a version."""
    import shutil

    source, target = agents_dir / src, agents_dir / into
    if not (source / "system.md").exists():
        raise FileNotFoundError(f"no agent at {source}")
    if target.exists():
        raise FileExistsError(f"{target} exists; a version is never overwritten")
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("optimise.json"))
    cfg = yaml.safe_load((source / "agent.yaml").read_text()) or {}
    was = cfg.get("model", "haiku")
    cfg["model"] = model
    cfg.pop("challenger_of", None)
    cfg["measured_against"] = src
    header = [ln for ln in (source / "agent.yaml").read_text().split("\n") if ln.startswith("#")]
    (target / "agent.yaml").write_text(
        "\n".join(
            [
                f"# {into}: {src}'s prompt files on {model} (was {was}); a model switch, not a round",
                *header,
            ]
        )
        + "\n"
        + yaml.safe_dump(cfg, sort_keys=False)
    )
    return target
