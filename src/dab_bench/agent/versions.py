"""Agent versions are folders: `agents/<name>/{system.md, agent.yaml, helper.py}`.

`system.md` and `helper.py` are the surfaces a later optimiser edits; `agent.yaml`
is frozen across a comparison so it is between prompts, not budgets. The
fingerprint is what a run is logged against. `agents/champion` is a one-line
pointer file naming the current champion version (`dab promote` moves it).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from dab_bench.config import AGENTS_DIR

SURFACES = ("system.md", "helper.py")
FROZEN = ("agent.yaml",)
CHAMPION_FILE = AGENTS_DIR / "champion"


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


@dataclass(frozen=True)
class AgentVersion:
    name: str
    path: Path
    system_prompt: str
    config: AgentConfig
    helper: str | None
    fingerprint: str

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
        return out


def fingerprint_dir(path: Path) -> str:
    h = hashlib.sha256()
    for name in sorted(SURFACES + FROZEN):
        p = path / name
        if p.exists():
            h.update(name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


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
    )


def champion_name() -> str:
    return CHAMPION_FILE.read_text().strip() if CHAMPION_FILE.exists() else "v0"


def list_versions() -> list[str]:
    if not AGENTS_DIR.exists():
        return []
    return sorted(
        p.name
        for p in AGENTS_DIR.iterdir()
        if p.is_dir() and (p / "system.md").exists() and p.name != "curator"
    )
