"""`execute_python` runs in a Docker container with no network at all (decision D3 A).

One container per trial (`docker run -d --network none`), started on the
trial's first `execute_python` and removed when the trial ends, with only that
trial's working directory mounted (at `/work/<trial_key>`): a trial never sees
another trial's files, so trials of the same query stay independent. One fresh
Python process per call. Data reaches
the container only as files: `query_db(sql, save_as="x")` writes
`/work/x.parquet` and the code reads it with pandas or duckdb. No database
credential is ever inside the box, so the read-only role is the only way to
the data. The image is `infra/sandbox.Dockerfile` (`make sandbox`).
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from dab_bench.config import WORKSPACE_DIR

IMAGE = "dab-sandbox:py312"
OUTPUT_CUT = 10_000


class SandboxError(RuntimeError):
    pass


def image_exists() -> bool:
    if not shutil.which("docker"):
        return False
    r = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, text=True)
    return r.returncode == 0


def build_image(dockerfile: Path) -> None:
    subprocess.run(
        ["docker", "build", "-t", IMAGE, "-f", str(dockerfile), str(dockerfile.parent)],
        check=True,
    )


@dataclass
class Sandbox:
    """One run's workspace, and a container per trial that is using it."""

    name: str  # the run's container-name prefix
    workspace: Path  # host path; each trial's subdirectory is mounted into its own container
    live: dict[str, str] = field(default_factory=dict)  # trial_key -> container name

    @classmethod
    def start(cls, run_id: str, workspace: Path | None = None) -> Sandbox:
        if not image_exists():
            raise SandboxError(f"docker image {IMAGE} missing — run `make sandbox`")
        ws = workspace or (WORKSPACE_DIR / run_id)
        ws.mkdir(parents=True, exist_ok=True)
        return cls(name=f"dab-sbx-{run_id}"[:40].replace(":", "-"), workspace=ws)

    def _container(self, trial_key: str) -> str:
        """The trial's container, started on first use with only its own directory mounted."""
        if trial_key in self.live:
            return self.live[trial_key]
        d = self.trial_dir(trial_key)
        digest = hashlib.sha1(f"{self.workspace}:{trial_key}".encode()).hexdigest()[:12]
        name = f"dab-sbx-{digest}"
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        r = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "--label",
                f"dab.run={self.name}",
                "--network",
                "none",
                "--memory",
                "4g",
                "--cpus",
                "2",
                "--pids-limit",
                "256",
                "-v",
                f"{d}:/work/{trial_key}",
                "-w",
                f"/work/{trial_key}",
                IMAGE,
                "sleep",
                "infinity",
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            raise SandboxError(f"docker run failed: {r.stderr.strip()[:400]}")
        self.live[trial_key] = name
        return name

    def trial_dir(self, trial_key: str) -> Path:
        d = self.workspace / trial_key
        d.mkdir(parents=True, exist_ok=True)
        return d

    def run(self, code: str, trial_key: str, timeout_s: int = 600) -> tuple[str, float]:
        """Execute `code` with cwd `/work/<trial_key>`; return (output, seconds)."""
        container = self._container(trial_key)
        t0 = time.time()
        try:
            r = subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    "-w",
                    f"/work/{trial_key}",
                    container,
                    "python",
                    "-c",
                    code,
                ],
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            subprocess.run(
                ["docker", "exec", container, "pkill", "-f", "python -c"], capture_output=True
            )
            return (
                f"Error (TimeoutError): execution exceeded {timeout_s}s. Simplify the code.",
                time.time() - t0,
            )
        out = r.stdout
        if r.stderr.strip():
            err = r.stderr.strip()
            if r.returncode != 0:
                # keep the last lines: the traceback's actual error
                lines = err.splitlines()
                err = "\n".join(lines[-12:])
                out = (out + "\n" if out else "") + f"Error (exit {r.returncode}):\n{err}"
            else:
                out = (out + "\n" if out else "") + f"[stderr] {err[-2000:]}"
        return out, time.time() - t0

    def release(self, trial_key: str) -> None:
        """Remove the trial's container; its files stay in the workspace for the run record."""
        name = self.live.pop(trial_key, None)
        if name:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)

    def stop(self) -> None:
        for key in list(self.live):
            self.release(key)


def cut(text: str, limit: int = OUTPUT_CUT) -> str:
    if len(text) <= limit:
        return text
    head, tail = int(limit * 0.6), int(limit * 0.3)
    return text[:head] + f"\n…[{len(text) - head - tail} chars cut]…\n" + text[-tail:]
