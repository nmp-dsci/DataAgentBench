import time
from pathlib import Path

from dab_bench.eval.validators import judge, load_validator


def _write(path: Path, src: str) -> Path:
    path.mkdir(parents=True)
    (path / "validate.py").write_text(src)
    return path


def test_pass_and_fail_with_reason(tmp_path: Path) -> None:
    qdir = _write(
        tmp_path / "query_x" / "query1",
        "def validate(s):\n    return ('7' in s, 'found' if '7' in s else 'no 7')\n",
    )
    fn = load_validator(qdir, tmp_path)
    assert judge(fn, "the answer is 7") == judge(fn, "7")
    assert judge(fn, "7").ok is True
    v = judge(fn, "8")
    assert v.ok is False and v.reason == "no 7" and v.timed_out is False


def test_timeout_is_a_fail_not_a_hang(tmp_path: Path) -> None:
    qdir = _write(
        tmp_path / "query_x" / "query2",
        "import time\n\ndef validate(s):\n    while True:\n        time.sleep(0.05)\n",
    )
    fn = load_validator(qdir, tmp_path)
    t0 = time.time()
    v = judge(fn, "anything", timeout_s=1)
    assert v.timed_out is True and v.ok is False
    assert time.time() - t0 < 3


def test_exception_is_recorded(tmp_path: Path) -> None:
    qdir = _write(
        tmp_path / "query_x" / "query3", "def validate(s):\n    raise ValueError('bad')\n"
    )
    fn = load_validator(qdir, tmp_path)
    v = judge(fn, "x")
    assert v.ok is False and v.error == "ValueError" and "bad" in v.reason


def test_common_scaffold_is_importable_from_upstream_root(tmp_path: Path) -> None:
    (tmp_path / "common_scaffold" / "validate").mkdir(parents=True)
    (tmp_path / "common_scaffold" / "__init__.py").write_text("")
    (tmp_path / "common_scaffold" / "validate" / "__init__.py").write_text("")
    (tmp_path / "common_scaffold" / "validate" / "levenshtein.py").write_text(
        "def levenshtein(a, b):\n    return abs(len(a) - len(b))\n"
    )
    qdir = _write(
        tmp_path / "query_x" / "query4",
        "from common_scaffold.validate.levenshtein import levenshtein\n\ndef validate(s):\n    return (levenshtein(s, 'abc') <= 1, '')\n",
    )
    fn = load_validator(qdir, tmp_path)
    assert judge(fn, "abcd").ok is True and judge(fn, "abcdef").ok is False
