"""G1 (plan s11, D40 B): the decisive-interpretation reviewer.

The leaderboard rubric (§2.2) flags prompt text that hands the agent "a decisive value, label,
threshold, key, cardinality or interpretation choice" a gold answer depends on. The literal
guard (`eval/guards.py`) only sees copies: a gold value, question words, golden SQL. The
reviewer (`agents/reviewer/`, Opus 5.5) reads each write the optimiser makes beside the
questions it could affect and their gold answers, and says whether it decides one of them.
A decisive verdict refuses the write like any leak: the optimiser is told what decided it
(redacted) and may try once more.

It is a checker, never a writer: its verdicts go to `optimise.json`, never into a prompt.
When the reviewer fails (a timeout, no verdict), the write is accepted and recorded as
unreviewed; G2's audit still runs over the finished text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dab_bench.config import AGENTS_DIR

REVIEWER_DIR = AGENTS_DIR / "reviewer"
GOLD_CHARS = 600  # of each gold answer shown to the reviewer

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decisive": {"type": "boolean"},
        "question": {"type": "string", "description": "the id of the question most affected"},
        "what": {"type": "string", "description": "the deciding part, in your own words"},
        "reason": {"type": "string"},
    },
    "required": ["decisive", "reason"],
}


@dataclass
class Question:
    qid: str
    question: str
    gold: str


def questions_for(dataset: str | None) -> list[Question]:
    """The released questions a text could affect: one dataset's, or all 54 for a playbook
    section (`dataset` None)."""
    from dab_bench.data.index import load

    out = []
    for q in load().queries:
        if not q.get("released", True):
            continue
        qid = str(q["id"])
        if dataset is None or qid.split("/")[0] == dataset:
            out.append(Question(qid, q["question"], q.get("gold_text") or ""))
    return out


def message(text: str, kind: str, qs: list[Question]) -> str:
    what = (
        "a playbook section: every dataset's agent reads it"
        if kind == "component"
        else "the notes for one dataset: its agent reads them for every question"
    )
    parts = [
        f"## The text (kind: {what})\n\n````\n{text.strip()}\n````",
        f"## The questions it could affect ({len(qs)}), with their gold answers",
    ]
    for q in qs:
        gold = q.gold.strip()
        if len(gold) > GOLD_CHARS:
            gold = gold[:GOLD_CHARS] + " …"
        parts.append(f"### {q.qid}\nQuestion: {q.question}\nGold answer:\n```\n{gold}\n```")
    return "\n\n".join(parts) + "\n"


async def review(
    text: str, kind: str, dataset: str | None, model: str | None = None
) -> tuple[list[str], dict[str, Any]]:
    """(problems, record) for one write: problems is empty unless the reviewer finds it
    decisive; the record goes to the session's `reviews`."""
    from dab_bench.eval.ledger import ask, redact

    qs = questions_for(dataset)
    c = await ask(
        (REVIEWER_DIR / "system.md").read_text(),
        message(text, kind, qs),
        SCHEMA,
        model=model,
        agent=REVIEWER_DIR.name,
        tool_name="write_verdict",
    )
    rec: dict[str, Any] = {"chars": len(text), "cost_usd": c.cost_usd, "n_turns": c.n_turns}
    if c.error or c.out is None:
        rec |= {"reviewed": False, "error": c.error}
        return [], rec
    golds = [(q.question, q.gold) for q in qs]
    what, _ = redact({"what": str(c.out.get("what") or "")[:300]}, golds)
    reason, _ = redact({"reason": str(c.out.get("reason") or "")[:400]}, golds)
    decisive = bool(c.out.get("decisive"))
    qid = str(c.out.get("question") or "").strip()
    rec |= {
        "reviewed": True,
        "decisive": decisive,
        "question": qid if decisive else "",
        "what": what["what"] if decisive else "",
        "reason": reason["reason"],
    }
    if not decisive:
        return [], rec
    return [
        f"G1 decisive for {qid or 'a question'}: {what['what'] or reason['reason']}; teach the "
        "method or the property of the data, not the choice that decides one answer"
    ], rec
