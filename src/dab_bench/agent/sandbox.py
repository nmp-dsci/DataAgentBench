"""`execute_python` runs in a Docker container with no network at all (decision D3 A).

One container per run (`docker run -d --network none`), one working directory
per trial mounted at `/work`, one fresh Python process per call. Data reaches
the container only as files: `query_db(sql, save_as="x")` writes
`/work/x.parquet` and the code reads it with pandas or duckdb. No database
credential is ever inside the box, so the read-only role is the only way to
the data. The image is `infra/sandbox.Dockerfile` (`make sandbox`).
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
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
    """A running container bound to one run's workspace directory."""

    name: str
    workspace: Path  # host path mounted at /work

    @classmethod
    def start(cls, run_id: str, workspace: Path | None = None) -> Sandbox:
        if not image_exists():
            raise SandboxError(f"docker image {IMAGE} missing — run `make sandbox`")
        ws = workspace or (WORKSPACE_DIR / run_id)
        ws.mkdir(parents=True, exist_ok=True)
        name = f"dab-sbx-{run_id}"[:63].replace(":", "-")
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        r = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "--network",
                "none",
                "--memory",
                "4g",
                "--cpus",
                "2",
                "--pids-limit",
                "256",
                "-v",
                f"{ws}:/work",
                "-w",
                "/work",
                IMAGE,
                "sleep",
                "infinity",
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            raise SandboxError(f"docker run failed: {r.stderr.strip()[:400]}")
        return cls(name=name, workspace=ws)

    def trial_dir(self, trial_key: str) -> Path:
        d = self.workspace / trial_key
        d.mkdir(parents=True, exist_ok=True)
        return d

    def run(self, code: str, trial_key: str, timeout_s: int = 600) -> tuple[str, float]:
        """Execute `code` with cwd `/work/<trial_key>`; return (output, seconds)."""
        self.trial_dir(trial_key)
        t0 = time.time()
        try:
            r = subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    "-w",
                    f"/work/{trial_key}",
                    self.name,
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
                ["docker", "exec", self.name, "pkill", "-f", "python -c"], capture_output=True
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

    def stop(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)


def cut(text: str, limit: int = OUTPUT_CUT) -> str:
    if len(text) <= limit:
        return text
    head, tail = int(limit * 0.6), int(limit * 0.3)
    return text[:head] + f"\n…[{len(text) - head - tail} chars cut]…\n" + text[-tail:]
