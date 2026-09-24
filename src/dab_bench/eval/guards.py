"""Leak guards for text written from the questions' failures (the optimiser's notes, D29).

The optimiser sees train questions, their golden SQL and their result diffs, so what it
writes could carry answers into a prompt. An edit is refused when it holds:

- **question text**: a run of 8 or more words from any of the 54 questions (the rule
  `tests/test_context.py` already holds the curated pack to);
- **a gold value**: a gold answer cell written literally, unless the question itself names
  it (the spike's gold-literal check, P1). A cell counts when it is at least 4 characters
  and not a bare number, or a decimal number; a `;`- or `|`-separated fragment of a cell
  counts too unless it is one bare word; the gold's header line names columns and is
  skipped;
- **golden SQL**: a run of 6 or more SQL tokens from any golden, unless every token in the
  run is an SQL keyword, punctuation, a number or a one- or two-letter alias (so
  `count ( * ) as n` is not a leak);
- **too much**: more than `max_chars` characters.

Each check returns readable reasons; an empty list means the text is clean.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

QUESTION_RUN = 8
SQL_RUN = 6
NOTES_MAX_CHARS = 1_500

_WORD = re.compile(r"[a-z0-9]+")
_SQL_TOKEN = re.compile(r"'[^']*'|\"[^\"]*\"|[a-z_][a-z0-9_]*|\d+(?:\.\d+)?|[^\sa-z0-9_]")
_SQL_WORDS = frozenset(
    [
        "select",
        "from",
        "where",
        "and",
        "or",
        "not",
        "in",
        "is",
        "null",
        "as",
        "on",
        "join",
        "left",
        "right",
        "inner",
        "outer",
        "full",
        "cross",
        "group",
        "by",
        "order",
        "having",
        "limit",
        "offset",
        "distinct",
        "case",
        "when",
        "then",
        "else",
        "end",
        "with",
        "union",
        "all",
        "asc",
        "desc",
        "count",
        "sum",
        "avg",
        "min",
        "max",
        "cast",
        "between",
        "like",
        "ilike",
        "exists",
        "true",
        "false",
        "over",
        "partition",
        "coalesce",
        "nullif",
        "lower",
        "upper",
        "trim",
        "int",
        "integer",
        "bigint",
        "numeric",
        "text",
        "float",
        "double",
        "precision",
        "date",
        "timestamp",
        "interval",
        "extract",
        "filter",
        "lateral",
        "using",
        "natural",
        "rank",
        "row_number",
        "dense_rank",
        "nulls",
        "first",
        "last",
    ]
)


def _ngrams(tokens: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def question_runs(text: str, questions: Iterable[str], n: int = QUESTION_RUN) -> list[str]:
    mine = _ngrams(_WORD.findall(text.lower()), n)
    hits = []
    for q in questions:
        common = mine & _ngrams(_WORD.findall(q.lower()), n)
        if common:
            hits.append(" ".join(sorted(common)[0]))
    return hits


def gold_cells(gold_text: str) -> set[str]:
    rows = list(csv.reader(io.StringIO(gold_text.lstrip("﻿"))))
    cells: set[str] = set()
    for row in rows[1:] if len(rows) > 1 else rows:
        for c in row:
            parts = [c] + [
                s for s in re.split(r"[;|]", c) if not re.fullmatch(r"\s*[A-Za-z]+\s*", s)
            ]  # a fragment of a list cell counts unless it is one bare word ("KEYS" of a title)
            for part in parts:
                p = part.strip().strip('"').lower()
                if not p:
                    continue
                if (len(p) >= 4 and not re.fullmatch(r"[\d.,-]+", p)) or re.fullmatch(
                    r"\d+\.\d+", p
                ):
                    cells.add(p)
    return cells


def gold_literals(text: str, golds: Iterable[tuple[str, str]]) -> list[str]:
    """`golds`: (question, gold_text) pairs. A cell the question itself names is allowed."""
    low = text.lower()
    hits: set[str] = set()
    for question, gold in golds:
        q = question.lower()
        for c in gold_cells(gold):
            if c in q:
                continue
            if re.search(r"(?<![a-z0-9])" + re.escape(c) + r"(?![a-z0-9])", low):
                hits.add(c)
    return sorted(hits)


def _sql_tokens(sql: str) -> list[str]:
    sql = re.sub(r"--[^\n]*", " ", sql)
    return _SQL_TOKEN.findall(sql.lower())


def _telling(gram: tuple[str, ...]) -> bool:
    """A run leaks only if it names something: a quoted literal, or an identifier of three or
    more characters that is not an SQL keyword (so `count ( * ) as n` does not count)."""
    return any(
        t[0] in "'\"" or (re.fullmatch(r"[a-z_][a-z0-9_]{2,}", t) and t not in _SQL_WORDS)
        for t in gram
    )


def golden_fragments(text: str, golden_sqls: Iterable[str], n: int = SQL_RUN) -> list[str]:
    mine = _ngrams(_sql_tokens(text), n)
    hits: set[str] = set()
    for sql in golden_sqls:
        for gram in mine & _ngrams(_sql_tokens(sql), n):
            if _telling(gram):
                hits.add(" ".join(gram))
    return sorted(hits)


@dataclass
class Guard:
    """Everything an edit is checked against, loaded once per optimisation round."""

    questions: list[str] = field(default_factory=list)
    golds: list[tuple[str, str]] = field(default_factory=list)
    golden_sqls: list[str] = field(default_factory=list)
    max_chars: int = NOTES_MAX_CHARS

    def leaks(self, problems: list[str]) -> list[str]:
        """The problems that are leaks (question text, gold values, golden SQL), not length."""
        return [p for p in problems if not p.endswith(f"the limit is {self.max_chars:,}")]

    def check(self, text: str) -> list[str]:
        problems = []
        if len(text) > self.max_chars:
            problems.append(f"{len(text):,} characters; the limit is {self.max_chars:,}")
        if runs := question_runs(text, self.questions):
            problems.append(
                f"question text ({QUESTION_RUN}+ words from a question): {'; '.join(runs[:3])}"
            )
        if cells := gold_literals(text, self.golds):
            problems.append(f"gold values written literally: {', '.join(cells[:5])}")
        if frags := golden_fragments(text, self.golden_sqls):
            problems.append(
                f"golden SQL copied ({SQL_RUN}+ tokens): {'; '.join(frags[:3])}; describe the "
                "pattern in words instead"
            )
        return problems


def load_guard(max_chars: int = NOTES_MAX_CHARS) -> Guard:
    """The 54 questions with their gold, and every current golden's SQL."""
    from dab_bench.data.index import load
    from dab_bench.eval import golden

    ix = load()
    qs = [q for q in ix.queries if q.get("released", True)]
    return Guard(
        questions=[q["question"] for q in qs],
        golds=[(q["question"], q.get("gold_text") or "") for q in qs],
        golden_sqls=[g["sql"] for g in golden.current().values()],
        max_chars=max_chars,
    )
