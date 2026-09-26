"""`dab history` (plan s13, D42 A): every question's record across the versions, for the optimiser.

Until s13 a round read only its parent's run. The history adds what came before, read from
**MLflow** (D42 A; the one place this project reads MLflow back — the run folders stay the
record, and `FolderSource` builds the same history from them for the parity check):

- the **versions**: the champion's lineage (its `challenger_of` / `measured_against` chain)
  and every round from the champion that lost to it, each with its newest complete run on
  the 54 (the eval run's `scorecard.json`, `results.jsonl` and `agent/` snapshot);
- per version, **what changed** from its parent: a round or a model switch, which datasets'
  notes, which playbook sections, and which questions each session of the round read;
- per question, the **timeline** (answer and SQL under each version, where the statement
  broke), each **flip** labelled (a prompt change for it, shared instructions, a model
  switch, or no change to its notes or break-step section: run noise or a side effect, H3),
  and for a question that passed before and fails now, **the last pass**: the version, the
  diff of its dataset's notes and of its break-step section since, and that version's own
  statement (D44 A, H2);
- the **attempts**: each round from the champion that lost, with what every session wrote,
  its refusals (a literal-guard refusal by kind only: its text can hold a gold value), and the
  questions it gained and lost (`eval/outcome.py`, read from the round's MLflow run).

A past **answer** is never read (H1): for a question without a golden, an answer that passed
is the gold answer. The history is written to `runs/<champion run>/history.json`; the
optimiser's sessions read it as text (`question_block`, `attempt_block`, capped by H4). It
never reaches the agent, the curator or the reviewer (H5).
"""

from __future__ import annotations

import difflib
import json
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import yaml

from dab_bench.config import AGENTS_DIR, RUNS_DIR

HISTORY_MAX = 1_500  # H4: the timeline and flips of one question
DIFF_MAX = 600  # H4: one diff
SQL_MAX = 1_500  # the statement that last passed
ATTEMPT_MAX = 2_000  # H4: the last-attempt block of one session
ROW_KEYS = ("answer", "sql", "decision", "breaks_at", "category")


@dataclass
class VersionRun:
    """One version as its newest complete run on the 54 shows it."""

    version: str
    run_id: str
    started_at: str
    config: dict[str, Any]  # the run's agent.yaml snapshot
    system_md: str
    notes: dict[str, str]
    rows: dict[str, dict[str, Any]]  # scorecard, trial 1: answer · sql · decision · breaks_at
    sql: dict[str, str]  # the agent's statement, trial 1 (never its answer: H1)
    goldened: set[str]  # questions with a golden


@dataclass
class Round:
    version: str
    record: dict[str, Any]  # optimise.json
    outcome: dict[str, Any] | None  # eval/outcome.py's, None before `dab promote` weighs it


class Source(Protocol):
    name: str

    def versions(self) -> list[VersionRun]: ...

    def rounds(self) -> dict[str, Round]: ...


# ── reading one run's files (both sources) ───────────────────────────────────


def _read_run(d: Path, run_id: str) -> VersionRun | None:
    """A version from a run folder (or its MLflow artifacts in one): None when it is not a
    complete full-split run of a version that submits SQL, or is a cross-fit fold."""
    try:
        meta = json.loads((d / "run.json").read_text())
        card = json.loads((d / "scorecard.json").read_text())
        cfg = yaml.safe_load((d / "agent" / "agent.yaml").read_text()) or {}
    except (OSError, ValueError):
        return None
    s = meta.get("summary") or {}
    if (
        meta.get("split") != "all"
        or meta.get("dry_run")
        or not s
        or s.get("scored") != s.get("n")
        or s.get("rate_limited")
        or cfg.get("crossfit_of")
    ):
        return None
    rows = {
        q["query_id"]: {k: q.get(k) for k in ROW_KEYS}
        for q in card.get("questions", [])
        if q.get("trial", 1) == 1
    }
    if not any(r["sql"] is not None for r in rows.values()):
        return None  # v0: no statement to follow
    goldened = {
        q["query_id"]
        for q in card.get("questions", [])
        if q.get("trial", 1) == 1 and q.get("golden_id") is not None
    }
    sql = {}
    rp = d / "results.jsonl"
    for line in rp.read_text().splitlines() if rp.exists() else []:
        if line.strip():
            r = json.loads(line)
            if r.get("trial") == 1:
                sql[r["query_id"]] = r.get("agent_sql") or ""
    ag = d / "agent"
    notes = {p.stem: p.read_text() for p in sorted((ag / "datasets").glob("*.md"))}
    return VersionRun(
        version=str(meta["agent"]),
        run_id=run_id,
        started_at=str(meta["started_at"]),
        config=cfg,
        system_md=(ag / "system.md").read_text() if (ag / "system.md").exists() else "",
        notes=notes,
        rows=rows,
        sql=sql,
        goldened=goldened,
    )


def _newest(vs: list[VersionRun]) -> list[VersionRun]:
    best: dict[str, VersionRun] = {}
    for v in vs:
        if v.version not in best or v.started_at > best[v.version].started_at:
            best[v.version] = v
    return sorted(best.values(), key=lambda v: v.started_at)


class FolderSource:
    """The history from the run and agent folders: the record, and the parity check's side."""

    name = "folders"

    def __init__(self, runs_dir: Path = RUNS_DIR, agents_dir: Path = AGENTS_DIR) -> None:
        self.runs_dir, self.agents_dir = runs_dir, agents_dir

    def versions(self) -> list[VersionRun]:
        found = []
        for d in sorted(self.runs_dir.iterdir()) if self.runs_dir.exists() else []:
            v = _read_run(d, d.name)
            if v is not None:
                found.append(v)
        return _newest(found)

    def rounds(self) -> dict[str, Round]:
        from dab_bench.eval.outcome import all_outcomes

        return {
            rec["version"]: Round(rec["version"], rec, out)
            for rec, out in all_outcomes(self.agents_dir, self.runs_dir)
        }


class MlflowSource:
    """The history from the central MLflow (D42 A): eval runs (`kind=eval`, `split=all`) and
    their artifacts, round runs (`kind=optimise`) with `optimise.json` and the `outcome.json`
    `dab promote` wrote. `client` is an `MlflowClient` (a stand-in in tests)."""

    name = "mlflow"

    def __init__(self, client: Any = None, experiment_id: str | None = None) -> None:
        import os

        # the central server advertises multipart downloads, whose presigned URLs name MinIO by
        # its compose hostname: unreachable from the host, so each download retries for minutes.
        # The server's own proxy serves the same bytes. No progress bars either.
        os.environ.setdefault("MLFLOW_ENABLE_PROXY_MULTIPART_DOWNLOAD", "false")
        os.environ.setdefault("MLFLOW_ENABLE_ARTIFACTS_PROGRESS_BAR", "false")
        if client is None:
            import mlflow
            from mlflow import MlflowClient

            from dab_bench.config import MLFLOW_EXPERIMENT
            from dab_bench.tracking.mlflow_log import _client_setup

            _client_setup()
            client = MlflowClient()
            exp = mlflow.get_experiment_by_name(MLFLOW_EXPERIMENT)
            if exp is None:
                raise RuntimeError(f"MLflow has no experiment {MLFLOW_EXPERIMENT}")
            experiment_id = exp.experiment_id
        self.client, self.experiment_id = client, experiment_id

    def _search(self, kind: str, extra: str = "") -> list[Any]:
        return list(
            self.client.search_runs(
                [self.experiment_id],
                filter_string=f"tags.kind = '{kind}'" + extra,
                max_results=1000,
            )
        )

    @contextmanager
    def _files(self, run_id: str, paths: list[str]) -> Iterator[Path]:
        with tempfile.TemporaryDirectory() as tmp:
            for p in paths:
                try:
                    self.client.download_artifacts(run_id, p, tmp)
                except Exception:  # noqa: BLE001, S112 - a missing artifact leaves the run out
                    continue
            yield Path(tmp)

    def versions(self) -> list[VersionRun]:
        found = []
        for r in self._search("eval", " and tags.split = 'all'"):
            with self._files(
                r.info.run_id, ["run.json", "scorecard.json", "results.jsonl", "agent"]
            ) as d:
                name = (r.data.tags or {}).get("mlflow.runName") or r.info.run_id
                v = _read_run(d, name)
            if v is not None:
                found.append(v)
        return _newest(found)

    def rounds(self) -> dict[str, Round]:
        newest: dict[str, Any] = {}
        for r in self._search("optimise"):
            agent = (r.data.tags or {}).get("agent")
            if agent and (agent not in newest or r.info.start_time > newest[agent].info.start_time):
                newest[agent] = r
        out = {}
        for agent, r in newest.items():
            with self._files(r.info.run_id, ["optimise.json", "outcome.json"]) as d:
                if not (d / "optimise.json").exists():
                    continue
                rec = json.loads((d / "optimise.json").read_text())
                if rec.get("crossfit"):
                    continue
                o = d / "outcome.json"
                outcome = json.loads(o.read_text()) if o.exists() else None
            rec.setdefault("version", agent)
            out[agent] = Round(agent, rec, outcome)
        return out


# ── the history ──────────────────────────────────────────────────────────────


def _parent(v: VersionRun) -> str | None:
    return v.config.get("challenger_of") or v.config.get("measured_against")


def _sections(system_md: str) -> dict[str, str]:
    from dab_bench.agent.optimise import sections

    return sections(system_md)


def _outside_sections(system_md: str) -> str:
    from dab_bench.agent.optimise import fill_sections

    return fill_sections(system_md, dict.fromkeys(_sections(system_md), ""))


def change(v: VersionRun, p: VersionRun | None, rnd: Round | None) -> dict[str, Any]:
    """What changed from the parent's prompt to this version's."""
    if p is None:
        return {"kind": "base"}
    sa, sb = _sections(p.system_md), _sections(v.system_md)
    read: dict[str, list[str]] = {}
    for s in (rnd.record.get("sessions") or []) if rnd else []:
        for q in s.get("questions") or []:
            read.setdefault(q, []).append(s["scope"])
    return {
        "kind": "round" if rnd else "model",
        "parent": p.version,
        "model": [p.config.get("model"), v.config.get("model")],
        "notes_changed": sorted(
            ds for ds in set(p.notes) | set(v.notes) if p.notes.get(ds, "") != v.notes.get(ds, "")
        ),
        "sections_changed": sorted(c for c in set(sa) | set(sb) if sa.get(c, "") != sb.get(c, "")),
        "shared_changed": _outside_sections(p.system_md) != _outside_sections(v.system_md),
        "read": read,
        "sessions": {
            s["scope"]: s.get("notes") is not None
            for s in (rnd.record.get("sessions") or [] if rnd else [])
        },
    }


def flip_label(q: str, ch: dict[str, Any], steps: set[str]) -> str:
    """H3: why a result may have flipped between a version and its parent."""
    if ch["kind"] == "model":
        return "model switch; prompt unchanged"
    if q.split("/")[0] in ch["notes_changed"] or steps & set(ch["sections_changed"]):
        return "prompt changed for it"
    if ch["shared_changed"]:
        return "shared instructions changed"
    return "no change to its notes or break-step section: run noise or a side effect"


def _diff(a: str, b: str) -> str:
    """The lines `a` had that `b` lacks ("was:") and the reverse ("now:"), half of DIFF_MAX
    each, so a long removal cannot hide what replaced it."""
    removed, added = [], []
    for ln in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0):
        if ln.startswith(("+++", "---")):
            continue
        if ln.startswith("-") and ln[1:].strip():
            removed.append("was: " + ln[1:])
        elif ln.startswith("+") and ln[1:].strip():
            added.append("now: " + ln[1:])
    half = DIFF_MAX // 2
    return "\n".join(x for x in (_cut("\n".join(removed), half), _cut("\n".join(added), half)) if x)


def _problem(p: str) -> str:
    """A refusal as the history shows it: a literal-guard hit by kind only (its text can hold a
    gold value, a question run or golden SQL); G1's words are already redacted."""
    if p.startswith("G1 ") or "characters; the limit is" in p or p.startswith("G3 "):
        return p
    return p.split(":", 1)[0]


def build(source: Source, champion: str) -> dict[str, Any]:
    vs = {v.version: v for v in source.versions()}
    rounds = source.rounds()
    if champion not in vs:
        raise ValueError(f"{champion} has no complete full-split run in {source.name}")
    line: list[str] = []
    v: str | None = champion
    while v and v in vs and v not in line:
        line.append(v)
        v = _parent(vs[v])
    line.reverse()
    attempts = [
        name
        for name, r in rounds.items()
        if r.record.get("challenger_of") == champion
        and name in vs
        and (r.outcome or {}).get("outcome") == "lost"
    ]
    order = sorted(line + attempts, key=lambda n: vs[n].started_at)
    changes: dict[str, dict[str, Any]] = {
        n: change(vs[n], vs.get(_parent(vs[n]) or ""), rounds.get(n))
        if n != line[0]
        else {"kind": "base"}
        for n in order
    }
    champ = vs[champion]
    questions: dict[str, Any] = {}
    for q, crow in sorted(champ.rows.items()):
        col = (
            "answer"
            if crow["answer"] is False
            else "sql"
            if crow["sql"] is False
            else "sql"
            if crow["sql"] is not None
            else "answer"
        )
        timeline = []
        for n in order:
            r = vs[n].rows.get(q) or {}
            entry: dict[str, Any] = {
                "version": n,
                "answer": r.get("answer"),
                "sql": r.get("sql"),
                "breaks_at": r.get("breaks_at"),
            }
            p = vs.get(_parent(vs[n]) or "")
            ch = changes[n]
            if ch["kind"] != "base" and p is not None:
                before, now = (p.rows.get(q) or {}).get(col), r.get(col)
                if before is not None and now is not None and before != now:
                    steps = {
                        x for x in (r.get("breaks_at"), (p.rows.get(q) or {}).get("breaks_at")) if x
                    }
                    entry["flip"] = flip_label(q, ch, steps)
                entry["read_by"] = ch.get("read", {}).get(q, [])
            timeline.append(entry)
        passed_before = [n for n in line[:-1] if (vs[n].rows.get(q) or {}).get(col) is True]
        status = (
            "passing"
            if crow[col] is True
            else "regressed"
            if passed_before
            else "never"
            if crow[col] is False
            else "unscored"
        )
        item: dict[str, Any] = {"tracked": col, "status": status, "timeline": timeline}
        if status == "regressed":
            lp = vs[passed_before[-1]]
            ds = q.split("/")[0]
            step = crow.get("breaks_at")
            item["last_passed"] = {
                "version": lp.version,
                "run_id": lp.run_id,
                "sql": (lp.sql.get(q) or "")[:SQL_MAX],
                "notes_diff": _diff(lp.notes.get(ds, ""), champ.notes.get(ds, "")),
                "section": step,
                "section_diff": _diff(
                    _sections(lp.system_md).get(step, ""), _sections(champ.system_md).get(step, "")
                )
                if step
                else "",
            }
        questions[q] = item
    return {
        "built_at": datetime.now(UTC).isoformat(),
        "source": source.name,
        "champion": champion,
        "champion_run": champ.run_id,
        "versions": [
            {
                "version": n,
                "run_id": vs[n].run_id,
                "started_at": vs[n].started_at,
                "model": vs[n].config.get("model"),
                "role": "champion" if n == champion else "attempt" if n in attempts else "lineage",
                "change": changes[n],
            }
            for n in order
        ],
        "questions": questions,
        "attempts": [_attempt(rounds[a]) for a in sorted(attempts, key=lambda n: vs[n].started_at)],
    }


def _attempt(r: Round) -> dict[str, Any]:
    return {
        "version": r.version,
        "outcome": r.outcome,
        "method": r.record.get("method"),
        "sessions": [
            {
                "scope": s["scope"],
                "kind": s.get("kind") or "dataset",
                "questions": s.get("questions") or [],
                "accepted": s.get("notes") is not None,
                "text": s.get("notes"),
                "rationale": s.get("rationale") or "",
                "refusals": [_problem(p) for x in s.get("refusals") or [] for p in x["problems"]],
            }
            for s in r.record.get("sessions") or []
        ],
    }


# ── as the optimiser reads it ────────────────────────────────────────────────


def _mark(v: bool | None) -> str:
    return "—" if v is None else "pass" if v else "FAIL"


def _cut(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def question_block(h: dict[str, Any], q: str) -> str:
    """One question's history as a session reads it (H4: the timeline ≤ 1,500 characters,
    each diff ≤ 600, the statement ≤ 1,500)."""
    item = (h.get("questions") or {}).get(q)
    if not item:
        return ""
    models = {v["version"]: v for v in h["versions"]}
    lines = []
    for e in item["timeline"]:
        v = models[e["version"]]
        tag = " ★" if v["role"] == "champion" else " ✗" if v["role"] == "attempt" else ""
        ch = v["change"]
        what = (
            "—"
            if ch["kind"] == "base"
            else f"model switch from {ch['parent']}"
            if ch["kind"] == "model"
            else f"round from {ch['parent']}"
            + (f"; read by {', '.join(e['read_by'])}" if e.get("read_by") else "; not read")
        )
        brk = f"; breaks at {e['breaks_at']}" if e.get("breaks_at") else ""
        flip = f" · flipped: {e['flip']}" if e.get("flip") else ""
        lines.append(
            f"{e['version']}{tag} ({v['model']}): answer {_mark(e['answer'])} · SQL "
            f"{_mark(e['sql'])}{brk} · {what}{flip}"
        )
    head = (
        f"History of {q} (one trial per version; ★ champion, ✗ lost to it; "
        f"tracking its {'SQL' if item['tracked'] == 'sql' else 'answer'}):"
    )
    out = [head, _cut("\n".join(lines), HISTORY_MAX)]
    lp = item.get("last_passed")
    if lp:
        out.append(f"Last passed under {lp['version']}. What changed since, for this question:")
        out.append(
            f"- {q.split('/')[0]} notes, {lp['version']} → {h['champion']}:\n"
            + (lp["notes_diff"] or "(unchanged)")
        )
        if lp.get("section"):
            out.append(
                f"- the {lp['section']} section (the step it breaks at now):\n"
                + (lp["section_diff"] or "(unchanged)")
            )
        if lp.get("sql"):
            out.append(
                f"The statement that passed under {lp['version']} (the agent's own; its answer "
                "is not shown):\n```sql\n" + lp["sql"] + "\n```"
            )
    return "\n".join(out)


def attempt_block(h: dict[str, Any], scope: str) -> str:
    """For one session (a dataset, or `playbook:<step>`): each round from the champion that
    lost — what it wrote for the same scope, the refusals, and its gains and losses (H4:
    ≤ 2,000 characters a round)."""
    parts = []
    for a in h.get("attempts") or []:
        o = a.get("outcome") or {}
        vp = o.get("vs_parent") or {}
        lines = [f"### {a['version']}: a round from {h['champion']} that lost to it"]
        if vp:
            ans, sql = vp.get("answer", {}), vp.get("sql", {})
            lines.append(
                f"Result against {h['champion']}: answers {ans.get('before')}→{ans.get('after')} "
                f"of {ans.get('n')}, SQL {sql.get('before')}→{sql.get('after')} of {sql.get('n')}."
            )
        s = next((x for x in a["sessions"] if x["scope"] == scope), None)
        if s is None:
            lines.append(f"It had no session for {scope}.")
        else:
            lines.append(
                f"Its {scope} session read {', '.join(s['questions']) or 'nothing'} and "
                + (
                    "wrote:"
                    if s["accepted"]
                    else f"had nothing accepted ({h['champion']}'s text kept)."
                )
            )
            if s["accepted"] and s["text"]:
                lines.append(_cut(s["text"], 700))
            if s["refusals"]:
                lines.append("Refusals: " + _cut("; ".join(s["refusals"]), 500))
            if s["rationale"]:
                lines.append("Its rationale: " + _cut(s["rationale"], 300))
        ds = None if scope.startswith("playbook:") else scope
        step = scope.removeprefix("playbook:") if ds is None else None
        for col in ("answer", "sql"):
            m = vp.get(col) or {}
            lost = [
                q
                for q in m.get("lost", [])
                if (ds and q.split("/")[0] == ds) or (step and m["lost_breaks_at"].get(q) == step)
            ]
            gained = [q for q in m.get("gained", []) if ds and q.split("/")[0] == ds]
            if lost:
                where = f" now breaking at {step}" if step else ""
                lines.append(
                    f"{col.upper()} lost here (passed under {h['champion']}){where}: {', '.join(lost)}."
                )
            if gained:
                lines.append(f"{col.upper()} gained here: {', '.join(gained)}.")
        parts.append(_cut("\n".join(lines), ATTEMPT_MAX))
    return "\n\n".join(parts)


# ── the file ─────────────────────────────────────────────────────────────────


def path_for(run_id: str) -> Path:
    return RUNS_DIR / run_id / "history.json"


def write(h: dict[str, Any]) -> Path:
    p = path_for(h["champion_run"])
    p.write_text(json.dumps(h, ensure_ascii=False, indent=1) + "\n")
    return p


def load(run_id: str) -> dict[str, Any] | None:
    p = path_for(run_id)
    return json.loads(p.read_text()) if p.exists() else None


def parity(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """Where two histories (MLflow and the folders) differ, ignoring when each was built."""
    out = []
    for key in ("champion", "champion_run", "versions", "questions", "attempts"):
        if a.get(key) != b.get(key):
            if key == "questions":
                qs = sorted(q for q in set(a[key]) | set(b[key]) if a[key].get(q) != b[key].get(q))
                out.append(f"questions differ: {', '.join(qs[:8])}")
            else:
                out.append(f"{key} differ")
    return out
