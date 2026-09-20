"""Run a query's `validate.py` the way the benchmark does, with a timeout it does not have.

Each validator is a module with `validate(llm_output: str) -> (bool, str)`.
Nine of the 54 use `common_scaffold.validate.levenshtein`, a pure-Python
O(n·m) edit distance, and answers reach 13.8k characters, so a call can take
seconds; twenty (all out of scope) read `ground_truth.csv` beside them. The
runner imports the module from the upstream tree with the tree on `sys.path`,
and bounds every call with `signal.alarm`. It must therefore run on the main
thread of its process — `rescore` gives each task its own worker process.
"""

from __future__ import annotations

import importlib.util
import signal
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

Validator = Callable[[str], tuple[bool, str]]


class ValidatorTimeout(BaseException):
    """Raised by the alarm handler. A BaseException so a validator's `except Exception` cannot swallow it."""


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str
    timed_out: bool = False
    error: str | None = None


def query_dir(upstream_root: Path, folder: str, query_id: int) -> Path:
    return upstream_root / folder / f"query{query_id}"


def load_validator(qdir: Path, upstream_root: Path) -> Validator:
    """Import `<qdir>/validate.py` as its own module, with the upstream root importable for `common_scaffold`."""
    root = str(upstream_root)
    if root not in sys.path:
        sys.path.insert(0, root)
    name = "dab_validator_" + "_".join(qdir.relative_to(upstream_root).parts).replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, qdir / "validate.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {qdir / 'validate.py'}")
    module: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    fn = getattr(module, "validate", None)
    if not callable(fn):
        raise ImportError(f"{qdir / 'validate.py'} has no validate()")
    return fn  # type: ignore[no-any-return]


def _alarm(_signum: int, _frame: object) -> None:
    raise ValidatorTimeout


def judge(fn: Validator, answer: str, timeout_s: int = 30) -> Verdict:
    """One call, bounded. A timeout or an exception is a fail with the reason recorded, never a crash."""
    previous = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(timeout_s)
    try:
        result = fn(answer)
    except ValidatorTimeout:
        return Verdict(ok=False, reason=f"validator timed out after {timeout_s}s", timed_out=True)
    except Exception as e:  # noqa: BLE001 - the validator is arbitrary upstream code
        return Verdict(
            ok=False, reason=f"validator raised {type(e).__name__}: {e}", error=type(e).__name__
        )
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    try:
        ok, reason = result
    except (TypeError, ValueError):
        return Verdict(ok=bool(result), reason=f"non-tuple result {result!r}")
    return Verdict(ok=bool(ok), reason=str(reason))
