"""`make upstream`: a shallow clone of the benchmark with every LFS file left as a pointer.

Nothing the explorer needs is a database. The clone is a build input for
`ingest` and `rescore`; it is gitignored and the commit it sits at is recorded
in `data/index/source.json`, so an index can always be traced to its source.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from dab_bench.config import UPSTREAM_DIR, UPSTREAM_REPO, settings

LFS_POINTER_HEAD = b"version https://git-lfs.github.com/spec/v1"


@dataclass(frozen=True)
class Upstream:
    path: Path
    commit: str
    repo: str


def _git(args: list[str], cwd: Path | None = None) -> str:
    env = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1", "GIT_TERMINAL_PROMPT": "0"}
    out = subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


def head_commit(path: Path = UPSTREAM_DIR) -> str | None:
    if not (path / ".git").exists():
        return None
    return _git(["rev-parse", "HEAD"], cwd=path)


def is_lfs_pointer(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(len(LFS_POINTER_HEAD)) == LFS_POINTER_HEAD
    except OSError:
        return False


def clone(commit: str | None = None, path: Path = UPSTREAM_DIR, force: bool = False) -> Upstream:
    """Clone (or re-clone) upstream at `commit`, or at the tip of main when None.

    `GIT_LFS_SKIP_SMUDGE=1` keeps every `.db`, `.sql`, `.duckdb` and `.bson` as a
    130-byte pointer. A full-depth fetch is only needed when a specific commit
    is requested, because `--depth 1` cannot check out an arbitrary hash.
    """
    commit = commit or settings().upstream_commit
    if path.exists() and force:
        shutil.rmtree(path)
    if not (path / ".git").exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        if commit:
            _git(["clone", "--filter=blob:none", "--no-checkout", UPSTREAM_REPO, str(path)])
            _git(["checkout", "--quiet", commit], cwd=path)
        else:
            _git(["clone", "--depth", "1", UPSTREAM_REPO, str(path)])
    elif commit and head_commit(path) != commit:
        _git(["fetch", "--quiet", "origin", commit], cwd=path)
        _git(["checkout", "--quiet", commit], cwd=path)
    fetch_pinned(path)
    return Upstream(path=path, commit=head_commit(path) or "unknown", repo=UPSTREAM_REPO)


def fetch_pinned(path: Path = UPSTREAM_DIR) -> None:
    """Fetch each PR head a reference answer file is pinned to (`aliases.pinned_commits`).

    One commit each, depth 1, no checkout: the objects land in the clone and
    `show` reads the file from them, so the working tree stays at the ingested
    commit. GitHub serves a PR head by hash even when the PR never merged.
    """
    from dab_bench.data.aliases import pinned_commits

    missing = [c for c in pinned_commits() if not _has_commit(c, path)]
    if missing:
        _git(["fetch", "--quiet", "--depth", "1", "origin", *missing], cwd=path)


def _has_commit(commit: str, path: Path) -> bool:
    try:
        _git(["cat-file", "-e", f"{commit}^{{commit}}"], cwd=path)
    except subprocess.CalledProcessError:
        return False
    return True


def show(commit: str, file: str, path: Path = UPSTREAM_DIR) -> str | None:
    """`file` as it is at `commit`, or None when the commit has not been fetched."""
    if not _has_commit(commit, path):
        return None
    return _git(["show", f"{commit}:{file}"], cwd=path)


def require(path: Path = UPSTREAM_DIR) -> Upstream:
    """The clone as it is on disk, or a clear error telling the caller to run `make upstream`."""
    commit = head_commit(path)
    if commit is None:
        raise FileNotFoundError(f"no upstream clone at {path}; run `make upstream` first")
    return Upstream(path=path, commit=commit, repo=UPSTREAM_REPO)
