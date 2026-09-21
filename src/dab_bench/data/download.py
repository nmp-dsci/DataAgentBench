"""`dab data download`: the database files for the 12 released datasets, from Hugging Face.

Mirrors upstream `download.sh` for the in-scope files only: every manifest
entry the index lists is fetched with `hf_hub_download` into the same path
under `data/upstream/`, then verified against the manifest's sha256. Files
that already match are left alone, so re-running is cheap. Mongo dumps are
plain files in the git clone and need no download.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from dab_bench.config import HF_DATA_REPO, UPSTREAM_DIR
from dab_bench.data.stores import Store, load_stores


@dataclass
class DownloadReport:
    fetched: list[str] = field(default_factory=list)
    verified: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # not in the manifest (mongo dumps)
    failed: list[str] = field(default_factory=list)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def matches(path: Path, digest: str | None, size: int | None) -> bool:
    if not path.is_file() or digest is None:
        return False
    if size is not None and path.stat().st_size != size:
        return False
    return sha256_of(path) == digest


def needed(stores: list[Store]) -> list[Store]:
    return [
        s for s in stores if s.in_manifest and s.file and not matches(s.path, s.sha256, s.bytes)
    ]


def download(
    datasets: list[str] | None = None,
    repo_id: str = HF_DATA_REPO,
    dry_run: bool = False,
) -> DownloadReport:
    rep = DownloadReport()
    stores = load_stores()
    if datasets:
        stores = [s for s in stores if s.dataset in set(datasets)]
    for s in stores:
        if not s.in_manifest or not s.file:
            rep.skipped.append(f"{s.dataset}/{s.name}")
            continue
        if matches(s.path, s.sha256, s.bytes):
            rep.verified.append(f"{s.dataset}/{s.name}")
            continue
        rel = f"{s.folder}/{s.file}"
        if dry_run:
            rep.fetched.append(rel)
            continue
        from huggingface_hub import hf_hub_download

        s.path.parent.mkdir(parents=True, exist_ok=True)
        hf_hub_download(
            repo_id=repo_id,
            filename=rel,
            repo_type="dataset",
            local_dir=str(UPSTREAM_DIR),
        )
        if matches(s.path, s.sha256, s.bytes):
            rep.fetched.append(rel)
        else:
            rep.failed.append(rel)
    return rep
