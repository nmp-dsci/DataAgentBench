"""`dab version-model` (plan s08, D35 A): a version that differs from its source only in the model."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from dab_bench.agent.versions import copy_with_model
from dab_bench.config import AGENTS_DIR


def test_the_copy_keeps_the_prompt_and_changes_only_the_model(tmp_path: Path) -> None:
    shutil.copytree(AGENTS_DIR / "v2_sql", tmp_path / "v2_sql")
    copy_with_model("v2_sql", "v2_sonnet", "sonnet", agents_dir=tmp_path)
    new, old = tmp_path / "v2_sonnet", tmp_path / "v2_sql"
    assert (new / "system.md").read_text() == (old / "system.md").read_text()
    assert sorted(p.name for p in (new / "datasets").iterdir()) == sorted(
        p.name for p in (old / "datasets").iterdir()
    )
    assert not (new / "optimise.json").exists()  # not a round
    cfg, was = (
        yaml.safe_load((new / "agent.yaml").read_text()),
        yaml.safe_load((old / "agent.yaml").read_text()),
    )
    assert (
        cfg["model"] == "sonnet"
        and cfg["measured_against"] == "v2_sql"
        and "challenger_of" not in cfg
    )
    assert {k: v for k, v in cfg.items() if k not in ("model", "measured_against")} == {
        k: v for k, v in was.items() if k != "challenger_of" and k != "model"
    }
    with pytest.raises(FileExistsError):
        copy_with_model("v2_sql", "v2_sonnet", "sonnet", agents_dir=tmp_path)
