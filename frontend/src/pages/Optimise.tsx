import { Link, Outlet, useNavigate, useParams } from 'react-router-dom';
import { type Change, type RoundDetail, type RoundSummary, type Rounds, type Side, type Tally, type VersionNode, fmtInt, fmtUsd, useGet } from '../lib/api';
import { GoldDiff } from '../lib/golddiff';
import { Mark, rate } from '../lib/scorecard';
import { Loading, Rate } from '../lib/ui';
import { agentPath, optimisePath, questionPath, runPath, trialPath, useLens } from '../lib/url';

/**
 * Optimisation rounds, explored like runs. A round read a scored run (the diagnostic), wrote a
 * new version (the proposal) and that version's run is its outcome. The list is the lineage over
 * time; a round opens in place (`/optimise/<version>`) with the three steps, and its outcome is
 * read per question the way an experiment comparison reads a baseline against a candidate.
 */

const CHANGE_LABEL: Record<Change, string> = {
  improved: 'improved',
  regressed: 'regressed',
  held: 'held (passed both)',
  'still failing': 'still failing',
  'not scored': 'not scored',
};
const CHANGE_TONE: Record<Change, string> = { improved: 'ok', regressed: 'warn', held: '', 'still failing': 'no', 'not scored': 'no' };
const day = (iso: string | null | undefined) => (iso ? iso.slice(0, 10) : '—');
const signed = (n: number) => (n > 0 ? `+${n}` : n < 0 ? `−${-n}` : '±0');

// ── the list ───────────────────────────────────────────────────────────────

export function Optimise() {
  const { version } = useParams();
  const { data, error } = useGet<Rounds>('/api/optimise');
  if (!data) return <Loading error={error} />;
  const rounds = data.rounds;
  const last = rounds[rounds.length - 1];
  const lift = last ? last.changes.after - last.changes.before : 0;
  return (
    <>
      <p className="label">
        optimise · {rounds.length} round{rounds.length === 1 ? '' : 's'} · {data.versions.length} versions · champion <code>{data.champion}</code>
      </p>
      <h1>
        {last ? (
          <>
            {rounds.length === 1 ? 'One optimisation round' : `${rounds.length} optimisation rounds`}: the newest wrote {last.version} and moved the answers from {last.changes.before}/{last.changes.n} to{' '}
            <em>
              {last.changes.after}/{last.changes.n} ({signed(lift)})
            </em>
          </>
        ) : (
          <>No optimisation round has run yet</>
        )}
      </h1>
      <p className="lead">
        A round is <code>dab optimise &lt;run&gt; --into &lt;version&gt;</code>: the optimiser reads the run's failed training questions per dataset (the diagnostic), writes a new version's notes and <code>system.md</code> under leak guards (the proposal), and the new version's own run
        of the 54 is the outcome. Rounds chain, so the outcome of one is the diagnostic of the next. Pick a round to open it.
      </p>
      {data.versions.length > 0 && <LineageFig nodes={data.versions} rounds={rounds} champion={data.champion} open={version ?? null} />}
      <Outlet />
      <h2>
        Every round — {rounds.length}, {fmtUsd(rounds.reduce((s, r) => s + (r.cost_usd ?? 0), 0), 2)} of optimiser time
      </h2>
      {rounds.length === 0 ? (
        <p className="empty">
          No round yet: <code>dab optimise &lt;run&gt; --into &lt;version&gt;</code> writes one, then <code>dab eval --agent &lt;version&gt; --split all</code> gives it an outcome.
        </p>
      ) : (
        <RoundsTable rounds={rounds} open={version ?? null} />
      )}
    </>
  );
}

function RoundsTable({ rounds, open }: { rounds: RoundSummary[]; open: string | null }) {
  const nav = useNavigate();
  return (
    <div className="tw">
      <table>
        <thead>
          <tr>
            <th>Round (the version it wrote)</th>
            <th>Read</th>
            <th>Wrote</th>
            <th className="num">Answers before → after</th>
            <th className="num">Improved · regressed</th>
            <th>Train · held out</th>
            <th className="num">Cost</th>
            <th>Promoted</th>
          </tr>
        </thead>
        <tbody>
          {[...rounds].reverse().map((r) => {
            const tr = r.after?.by_split?.train;
            const ho = r.after?.by_split?.heldout;
            const btr = r.before?.by_split?.train;
            const bho = r.before?.by_split?.heldout;
            return (
              <tr key={r.version} className={`pickrow ${open === r.version ? 'cur' : ''}`} onClick={() => nav(optimisePath(r.version))}>
                <td className="sub">
                  <Link to={optimisePath(r.version)} onClick={(e) => e.stopPropagation()}>
                    {r.parent} → {r.version}
                  </Link>
                  <span className="path">
                    {day(r.started_at)} · {r.optimiser?.model} @ {r.optimiser?.effort}
                  </span>
                </td>
                <td className="small nw">
                  <Link to={runPath(r.source_run)} onClick={(e) => e.stopPropagation()} title={r.source_run}>
                    {r.parent}'s run
                  </Link>
                  <span className="path">{r.source_run.slice(0, 16)}</span>
                </td>
                <td className="small nw">
                  {r.notes_written}/{r.sessions} notes{r.system_md_changed ? ' + system.md' : ''}
                  <span className="path">{r.refusals} refusals</span>
                </td>
                <td className="num">
                  {r.changes.before}/{r.changes.n} → {r.outcome_run ? `${r.changes.after}/${r.changes.n}` : 'not run yet'}
                </td>
                <td className="num">{r.outcome_run ? `+${r.changes.improved} · −${r.changes.regressed}` : '—'}</td>
                <td className="small">
                  {btr && tr ? `${rate(btr.answer)} → ${rate(tr.answer)}` : '—'} · {bho && ho ? `${rate(bho.answer)} → ${rate(ho.answer)}` : '—'}
                </td>
                <td className="num">{fmtUsd(r.cost_usd, 2)}</td>
                <td>{r.promoted_at ? <span className="chip ok">champion {day(r.promoted_at)}</span> : <span className="small muted">no</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** The versions as a lineage, oldest left: a solid edge is an optimisation round, a dashed one a
 *  hand-built challenger measured against an earlier version. Each node carries its run's top line. */
function LineageFig({ nodes, rounds, champion, open }: { nodes: VersionNode[]; rounds: RoundSummary[]; champion: string; open: string | null }) {
  const nav = useNavigate();
  const order = [...nodes].sort((a, b) => (a.started_at ?? '9').localeCompare(b.started_at ?? '9'));
  const W = 1000;
  const nw = 170;
  const nh = 76;
  const gap = order.length > 1 ? (W - 40 - nw) / (order.length - 1) : 0;
  const x = new Map(order.map((n, i) => [n.version, 20 + i * gap]));
  const byVersion = new Map(rounds.map((r) => [r.version, r]));
  const edges = order.flatMap((n) => {
    const from = n.parent ?? n.measured_against;
    if (!from || !x.has(from)) return [];
    return [{ from, to: n.version, round: n.parent ? byVersion.get(n.version) : undefined }];
  });
  // an edge that skips a version arcs over it, so it needs headroom
  const arcs = edges.some((e) => (x.get(e.to) ?? 0) - (x.get(e.from) ?? 0) > gap + 1);
  const y = arcs ? 70 : 16;
  const H = y + nh + 16;
  return (
    <figure style={{ margin: 'var(--s5) 0 0' }}>
      <p className="label">Fig · every version, oldest left, with the top line of its newest run of the 54</p>
      <svg className="dia graph" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Agent versions as a lineage: optimisation rounds as solid edges, hand-built challengers as dashed edges, each version with answers passed of 54">
        <title>Version lineage</title>
        <defs>
          <marker id="garr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" fill="currentColor" />
          </marker>
        </defs>
        {edges.map((e) => {
          const x1 = (x.get(e.from) ?? 0) + nw;
          const x2 = x.get(e.to) ?? 0;
          const adjacent = x2 - x1 < gap + 1 - nw;
          const mid = (x1 + x2) / 2;
          const d = adjacent ? `M${x1},${y + nh / 2} L${x2 - 2},${y + nh / 2}` : `M${x1 - nw / 2},${y} C${x1 - nw / 2},${y - 50} ${x2 + nw / 2},${y - 50} ${x2 + nw / 2},${y - 2}`;
          const label = e.round ? `round · +${e.round.changes.improved} −${e.round.changes.regressed}` : 'hand-built challenger';
          return (
            <g key={`${e.from}-${e.to}`}>
              <title>
                {e.from} → {e.to}: {label}
              </title>
              <path className={`ed ${e.round ? 'hi' : 'dash'}`} d={d} />
              <text className="tx k" x={adjacent ? mid : (x1 - nw / 2 + x2 + nw / 2) / 2} y={adjacent ? y + nh / 2 - 8 : y - 44} textAnchor="middle">
                {label}
              </text>
            </g>
          );
        })}
        {order.map((n) => {
          const nx = x.get(n.version) ?? 0;
          const isRound = byVersion.has(n.version);
          const go = () => (isRound ? nav(optimisePath(n.version)) : nav(agentPath(n.version)));
          return (
            <g
              key={n.version}
              className="pick"
              role="button"
              tabIndex={0}
              aria-label={`${n.version}: ${n.passed ?? '—'} of ${n.scored ?? '—'}`}
              onClick={go}
              onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && go()}
            >
              <title>
                {n.version}@{n.fingerprint}: {n.passed != null ? `${n.passed}/${n.scored} answers` : 'no complete run'}
                {isRound ? ' · open its round' : ' · open the agent'}
              </title>
              <rect className={`nd ${n.version === champion ? 'hi' : ''}`} x={nx} y={y} width={nw} height={nh} rx={8} style={open === n.version ? { strokeWidth: 2.5 } : undefined} />
              <text className="tx" x={nx + nw / 2} y={y + 24} textAnchor="middle">
                {n.version}
              </text>
              <text className="tx k" x={nx + nw / 2} y={y + 45} textAnchor="middle">
                {n.passed != null ? `${n.passed}/${n.scored} answers` : 'not run'}
              </text>
              <text className="tx s" x={nx + nw / 2} y={y + 64} textAnchor="middle">
                {n.version === champion ? 'champion' : isRound ? 'from a round' : 'hand-built'}
              </text>
            </g>
          );
        })}
      </svg>
      <p className="small">
        Accent: the champion, and an optimisation round's edge; dashed: a version built by hand and measured against an earlier one. Click a version to open its round (or its agent page). Source: <code>agents/*/optimise.json</code>, <code>agents/promotions.jsonl</code>, each
        version's newest complete run in <code>runs/</code>.
      </p>
    </figure>
  );
}

// ── one round ──────────────────────────────────────────────────────────────

type View = 'diagnostic' | 'proposal' | 'outcome';

export function OptimiseRound() {
  const { version = '' } = useParams();
  const { data, error } = useGet<RoundDetail>(`/api/optimise/${version}`);
  const [sp, setLens] = useLens();
  const view = (sp.get('view') as View) ?? 'diagnostic';
  if (!data) return <Loading error={error} />;
  const s = data.summary;
  const rec = data.record;
  const leaks = rec.sessions.flatMap((x) => x.refusals).filter((r) => r.problems.some(isLeak)).length;
  const refusals = rec.sessions.reduce((n, x) => n + x.refusals.length, 0);
  const o = data.outcome;
  const steps: { key: View; n: string; title: string; body: string }[] = [
    {
      key: 'diagnostic',
      n: '1',
      title: 'Diagnostic',
      body: `${rec.challenger_of}'s run: answers ${rate(data.diagnostic.totals?.answer)} · SQL ${rate(data.diagnostic.totals?.sql)}; ${rec.sessions.filter((x) => x.scope !== 'system.md').reduce((n, x) => n + x.questions.length, 0)} failed train questions read`,
    },
    {
      key: 'proposal',
      n: '2',
      title: 'Proposal',
      body: `${s.notes_written} of ${s.sessions} dataset notes${s.system_md_changed ? ' + system.md' : ''}; ${refusals} refusals (${leaks} leaks), ${fmtUsd(rec.cost_usd, 2)}`,
    },
    {
      key: 'outcome',
      n: '3',
      title: 'Outcome',
      body: o ? `${o.all.before} → ${o.all.after} of ${o.all.n} answers; +${o.all.improved} −${o.all.regressed}; held out ${o.by_split.heldout ? `${o.by_split.heldout.before} → ${o.by_split.heldout.after}` : '—'}` : `${version} has no complete run yet`,
    },
  ];
  return (
    <section className="card round-open" aria-label={`optimisation round ${version}`}>
      <p className="label">
        round · {rec.challenger_of} → {version} · {day(rec.started_at)} · {rec.optimiser.model} @ {rec.optimiser.effort} · split {rec.split.train} train / {rec.split.heldout} held out ·{' '}
        <Link to={agentPath(version)}>the agent</Link> · <Link to={optimisePath()}>close</Link>
      </p>
      <h2>
        {version}: {o ? `${signed(o.all.after - o.all.before)} answers on the 54 (${o.all.before} → ${o.all.after}), ${o.all.improved} improved and ${o.all.regressed} regressed` : 'written, not yet run'}
        {s.promoted_at ? `; champion since ${day(s.promoted_at)}` : ''}
      </h2>
      <div className="steps3" role="tablist" aria-label="the round's three steps">
        {steps.map((st, i) => (
          <button key={st.key} type="button" role="tab" aria-selected={view === st.key} className={`step ${view === st.key ? 'on' : ''}`} onClick={() => setLens({ view: st.key === 'diagnostic' ? null : st.key, change: null })}>
            <span className="label">
              {st.n} · {st.title}
            </span>
            <span className="small">{st.body}</span>
            {i < steps.length - 1 && <span className="arrow" aria-hidden="true">→</span>}
          </button>
        ))}
      </div>
      {view === 'diagnostic' && <Diagnostic d={data} />}
      {view === 'proposal' && <Proposal d={data} />}
      {view === 'outcome' && (o ? <Outcome d={data} /> : <p className="empty">Run it: <code>dab eval --agent {version} --split all</code>. The outcome is its newest complete full-split run.</p>)}
    </section>
  );
}

const isLeak = (p: string) => !/characters; the limit is/.test(p);

// ── 1 · diagnostic ─────────────────────────────────────────────────────────

function Diagnostic({ d }: { d: RoundDetail }) {
  const src = d.diagnostic.run_id;
  const failed = d.questions.filter((q) => q.before && q.before.category !== 'solved');
  const cats = new Map<string, { read: number; train: number; held: number; none: number }>();
  for (const q of failed) {
    const c = q.before!.category || '—';
    if (c === 'solved') continue;
    const e = cats.get(c) ?? { read: 0, train: 0, held: 0, none: 0 };
    if (q.read) e.read++;
    else if (q.split === 'train') e.train++;
    else if (q.split === 'heldout') e.held++;
    else e.none++;
    cats.set(c, e);
  }
  const rows = [...cats.entries()].sort((a, b) => sum(b[1]) - sum(a[1]));
  const max = Math.max(1, ...rows.map(([, e]) => sum(e)));
  const W = 1000;
  const rowH = 30;
  const lx = 230;
  const bw = W - lx - 90;
  const H = rows.length * rowH + 16;
  const byDs = groupBy(d.questions, (q) => q.dataset);
  return (
    <>
      <p>
        What the optimiser was given: the scorecard of <Link to={runPath(src)} className="mono">{src}</Link> (answers {rate(d.diagnostic.totals?.answer)} · SQL {rate(d.diagnostic.totals?.sql)} · decision {rate(d.diagnostic.totals?.decision)}). Each dataset's session saw only that
        dataset's failed <i>training</i> questions, with the agent's SQL beside the golden and the result diff; held-out and no-golden questions were never shown.
      </p>
      <figure style={{ margin: 'var(--s4) 0 0' }}>
        <p className="label">Fig · every question the source run did not solve, by failure category</p>
        <svg className="dia" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Failure categories in the source run, split into questions the optimiser read, held-out questions and questions without a golden">
          <title>Failure categories in the source run</title>
          {rows.map(([c, e], i) => {
            const yy = 8 + i * rowH;
            const seg = [
              { k: 'read', v: e.read, cls: 'bar hi', label: 'read by the optimiser' },
              { k: 'train', v: e.train, cls: 'bar b', label: 'train, not read' },
              { k: 'held', v: e.held, cls: 'bar ho', label: 'held out, never shown' },
              { k: 'none', v: e.none, cls: 'bar', label: 'no golden' },
            ];
            let at = lx;
            return (
              <g key={c}>
                <title>
                  {c}: {sum(e)} — {seg.filter((s) => s.v).map((s) => `${s.v} ${s.label}`).join(', ')}
                </title>
                <text className="tx" x={lx - 10} y={yy + 18} textAnchor="end">
                  {c}
                </text>
                {seg.map((s) => {
                  const w = (bw * s.v) / max;
                  const r = s.v ? <rect key={s.k} className={s.cls} x={at} y={yy + 4} width={Math.max(0, w - 1)} height={rowH - 10} rx={2} /> : null;
                  at += w;
                  return r;
                })}
                <text className="tx k" x={at + 8} y={yy + 18}>
                  {sum(e)}
                </text>
              </g>
            );
          })}
        </svg>
        <p className="small">
          <span className="v-ok">Accent</span>: failed training questions a session read; outlined: held out, never shown to the optimiser; grey: no golden, answer-scored only (dark grey, if any: a training question no session read). Categories from{' '}
          <code>dab diagnose</code>.
        </p>
      </figure>
      <div className="tw" style={{ marginTop: 'var(--s4)' }}>
        <table>
          <thead>
            <tr>
              <th>Dataset</th>
              <th className="num">Answers</th>
              <th>Read by the optimiser (the source run's trials)</th>
              <th>Failing, held out (never shown)</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(byDs).map(([ds, qs]) => {
              const read = qs.filter((q) => q.read);
              const held = qs.filter((q) => q.split === 'heldout' && q.before && !q.before.answer);
              return (
                <tr key={ds}>
                  <td className="sub">{ds}</td>
                  <td className="num">
                    <Rate passed={qs.filter((q) => q.before?.answer).length} n={qs.length} />
                  </td>
                  <td className="small">
                    {read.length
                      ? read.map((q, i) => (
                          <span key={q.query_id}>
                            {i > 0 && ', '}
                            <Link to={trialPath(src, `${q.query_id}/t1`)}>{q.query_id}</Link> <span className="muted">({q.before?.category})</span>
                          </span>
                        ))
                      : '— (no session)'}
                  </td>
                  <td className="small">{held.map((q) => q.query_id).join(', ') || '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ── 2 · proposal ───────────────────────────────────────────────────────────

function Proposal({ d }: { d: RoundDetail }) {
  const rec = d.record;
  const version = rec.version;
  const sys = d.files.find((f) => f.name === 'system.md');
  const notes = d.files.filter((f) => f.name !== 'system.md');
  return (
    <>
      <p>
        One isolated {rec.optimiser.model} session per dataset (tools: <code>query_db</code> to check a claim, <code>write_notes</code> to finish) and one cross-dataset pass over <code>system.md</code>. Every write is checked for question text, gold values written literally and copied golden
        SQL, and for length; a refusal goes back to the session with its reasons, and a second <i>leak</i> refusal drops the notes.
      </p>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>Session</th>
              <th>Failed train questions it read</th>
              <th>Outcome</th>
              <th className="num">Chars</th>
              <th className="num">Refusals · leaks</th>
              <th className="num">Turns</th>
              <th className="num">Cost</th>
              <th>Rationale and notes</th>
            </tr>
          </thead>
          <tbody>
            {rec.sessions.map((s) => {
              const leak = s.refusals.filter((r) => r.problems.some(isLeak));
              return (
                <tr key={s.scope}>
                  <td className="sub">{s.scope}</td>
                  <td className="small">{s.questions.join(', ') || '—'}</td>
                  <td>{s.error ? <span className="chip warn">error</span> : s.notes != null ? <span className="chip ok">{s.notes ? 'written' : 'kept as is'}</span> : <span className="chip warn">dropped</span>}</td>
                  <td className="num">{fmtInt(s.notes?.length ?? 0)}</td>
                  <td className="num">
                    {s.refusals.length} · {leak.length}
                  </td>
                  <td className="num">{s.n_turns}</td>
                  <td className="num">{fmtUsd(s.cost_usd, 3)}</td>
                  <td className="small">
                    {s.error ?? s.rationale}
                    {s.notes && (
                      <details>
                        <summary>the notes</summary>
                        <pre className="wrap-any">{s.notes}</pre>
                      </details>
                    )}
                    {s.refusals.length > 0 && (
                      <details>
                        <summary>
                          {s.refusals.length} refusal{s.refusals.length === 1 ? '' : 's'}
                        </summary>
                        <ul className="tight">
                          {s.refusals.map((r, i) => (
                            <li key={i}>{r.problems.join('; ')}</li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {sys && (
        <>
          <p className="label" style={{ marginTop: 'var(--s5)' }}>
            agents/{version}/system.md · against {rec.challenger_of}
          </p>
          <GoldDiff lines={sys.diff} a={rec.challenger_of} b={version} />
        </>
      )}
      {notes.length > 0 && (
        <details style={{ marginTop: 'var(--s4)' }}>
          <summary>
            {notes.length} dataset notes file{notes.length === 1 ? '' : 's'}, each against {rec.challenger_of}
          </summary>
          {notes.map((f) => (
            <div key={f.name}>
              <p className="label">
                agents/{version}/{f.name} {f.added ? '· new' : ''}
              </p>
              <GoldDiff lines={f.diff} a={rec.challenger_of} b={version} />
            </div>
          ))}
        </details>
      )}
    </>
  );
}

// ── 3 · outcome ────────────────────────────────────────────────────────────

function Outcome({ d }: { d: RoundDetail }) {
  const o = d.outcome!;
  const s = d.summary;
  const [sp, setLens] = useLens();
  const filter = (sp.get('change') as Change | null) ?? null;
  const shown = d.questions.filter((q) => !filter || q.change === filter);
  const splits: [string, string][] = [
    ['train', 'train · the optimiser read their failures'],
    ['heldout', 'held out · never shown'],
    ['no golden', 'no golden · answer only'],
  ];
  return (
    <>
      <p>
        <Link to={runPath(s.source_run)} className="mono">{s.source_run}</Link> ({d.record.challenger_of}) against <Link to={runPath(s.outcome_run!)} className="mono">{s.outcome_run}</Link> ({d.record.version}), question by question. The held-out line is the test of whether the notes
        generalise.
      </p>
      <div className="filters" role="group" aria-label="filter questions by change">
        {(['improved', 'regressed', 'held', 'still failing'] as Change[]).map((c) => (
          <button key={c} type="button" className={`tog ${filter === c ? 'on' : ''}`} aria-pressed={filter === c} onClick={() => setLens({ change: filter === c ? null : c })}>
            {CHANGE_LABEL[c]} {o.all[c]}
          </button>
        ))}
        {filter && (
          <button type="button" className="tog" onClick={() => setLens({ change: null })}>
            every question ×
          </button>
        )}
      </div>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>Questions</th>
              <th className="num">n</th>
              <th className="num">Answers before → after</th>
              <th className="num">Improved</th>
              <th className="num">Regressed</th>
              <th className="num">Held</th>
              <th className="num">Still failing</th>
            </tr>
          </thead>
          <tbody>
            {splits
              .filter(([k]) => o.by_split[k])
              .map(([k, label]) => (
                <SplitRow key={k} label={label} t={o.by_split[k]} />
              ))}
            <SplitRow label="all 54" t={o.all} strong />
          </tbody>
        </table>
      </div>
      <OutcomeGrid d={d} />
      <Dumbbell by={o.by_dataset} />
      {o.category_moves.some((m) => m.from !== m.to) && (
        <div className="tw" style={{ marginTop: 'var(--s5)' }}>
          <table>
            <caption>How failure categories moved (questions whose category changed)</caption>
            <thead>
              <tr>
                <th>Before</th>
                <th>After</th>
                <th className="num">Questions</th>
              </tr>
            </thead>
            <tbody>
              {o.category_moves
                .filter((m) => m.from !== m.to)
                .map((m) => (
                  <tr key={`${m.from}→${m.to}`}>
                    <td className="sub">{m.from}</td>
                    <td className={m.to === 'solved' ? 'v-ok' : ''}>{m.to}</td>
                    <td className="num">{m.n}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
      <h3 style={{ marginTop: 'var(--s6)' }}>
        {filter ? `${shown.length} question${shown.length === 1 ? '' : 's'} ${CHANGE_LABEL[filter]}` : `Every question, ${shown.length}`}
      </h3>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>Question</th>
              <th>Split</th>
              <th>Before · {d.record.challenger_of}</th>
              <th>After · {d.record.version}</th>
              <th>Change</th>
              <th>Trials</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((q) => (
              <tr key={q.query_id} className={q.change === 'regressed' ? 'warnrow' : ''}>
                <td className="sub">
                  <Link to={questionPath(q.query_id)}>{q.query_id}</Link>
                  <span className="path">{q.question.slice(0, 90)}</span>
                </td>
                <td className="small">
                  {q.split ?? '—'}
                  {q.read ? ' · read' : ''}
                </td>
                <td>
                  <SideCell s={q.before} />
                </td>
                <td>
                  <SideCell s={q.after} />
                </td>
                <td>
                  <span className={`chip ${CHANGE_TONE[q.change]}`}>{CHANGE_LABEL[q.change]}</span>
                </td>
                <td className="small">
                  <Link to={trialPath(s.source_run, `${q.query_id}/t1`)}>before</Link> · <Link to={trialPath(s.outcome_run!, `${q.query_id}/t1`)}>after</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function SplitRow({ label, t, strong = false }: { label: string; t: Tally; strong?: boolean }) {
  return (
    <tr>
      <td className="sub">{strong ? <b>{label}</b> : label}</td>
      <td className="num">{t.n}</td>
      <td className="num">
        {t.before} → {t.after} <span className={t.after > t.before ? 'v-ok' : t.after < t.before ? 'v-warn' : 'muted'}>({signed(t.after - t.before)})</span>
      </td>
      <td className="num">{t.improved}</td>
      <td className="num">{t.regressed}</td>
      <td className="num">{t.held}</td>
      <td className="num">{t['still failing']}</td>
    </tr>
  );
}

function SideCell({ s }: { s: Side | null }) {
  if (!s) return <span className="small muted">not run</span>;
  return (
    <span className="small">
      <Mark v={s.answer} /> {s.category === 'solved' ? 'solved' : s.category || '—'}
    </span>
  );
}

/** Every question as a pair of cells, before over after, grouped by dataset: the per-example view an
 *  experiment comparison gives (a candidate against its baseline). Click a pair for the after trial. */
function OutcomeGrid({ d }: { d: RoundDetail }) {
  const nav = useNavigate();
  const s = d.summary;
  const byDs = Object.entries(groupBy(d.questions, (q) => q.dataset));
  const most = Math.max(...byDs.map(([, qs]) => qs.length));
  const lx = 170;
  const cw = 44;
  const W = Math.max(1000, lx + most * cw + 20);
  const rowH = 64;
  const H = byDs.length * rowH + 30;
  const cls = (v: boolean | null | undefined) => (v == null ? 'bar' : v ? 'bar hi' : 'bar pro');
  return (
    <figure style={{ margin: 'var(--s5) 0 0' }}>
      <p className="label">Fig · every question, before (top) over after (bottom), by dataset</p>
      <svg className="dia" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Per-question outcome grid: each question as two cells, before and after the round; passed in accent, failed in amber">
        <title>Per-question outcome, before and after</title>
        <text className="tx k" x={lx} y={18}>
          ▲ improved · ▼ regressed · top cell {d.record.challenger_of}, bottom cell {d.record.version}
        </text>
        {byDs.map(([ds, qs], i) => {
          const yy = 30 + i * rowH;
          return (
            <g key={ds}>
              <text className="tx" x={lx - 12} y={yy + 22} textAnchor="end">
                {ds}
              </text>
              {qs.map((q, j) => {
                const xx = lx + j * cw;
                const n = q.query_id.split('/')[1];
                return (
                  <g key={q.query_id} className="pt" style={{ cursor: 'pointer' }} onClick={() => nav(trialPath(s.outcome_run!, `${q.query_id}/t1`))}>
                    <title>
                      {q.query_id} ({q.split ?? '—'}): {CHANGE_LABEL[q.change]} · before {q.before?.answer ? 'pass' : 'fail'} ({q.before?.category}) · after {q.after?.answer ? 'pass' : 'fail'} ({q.after?.category})
                    </title>
                    <rect className={cls(q.before?.answer)} x={xx} y={yy} width={cw - 8} height={16} rx={2} />
                    <rect className={cls(q.after?.answer)} x={xx} y={yy + 18} width={cw - 8} height={16} rx={2} />
                    <text className="tx k" x={xx + (cw - 8) / 2} y={yy + 50} textAnchor="middle">
                      {q.change === 'improved' ? `▲${n}` : q.change === 'regressed' ? `▼${n}` : n}
                    </text>
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
      <p className="small">
        Each pair is one question: the top cell is the source run, the bottom the outcome run; <span className="v-ok">accent</span> passed, <span className="v-warn">amber</span> failed. ▲ and ▼ mark the questions that changed. Hover for the split and category; click for the trial.
      </p>
    </figure>
  );
}

/** Per dataset, answers passed before (open dot) and after (filled), on the dataset's own share. */
function Dumbbell({ by }: { by: Record<string, Tally> }) {
  const rows = Object.entries(by);
  const W = 1000;
  const lx = 190;
  const rx = W - 110;
  const rowH = 30;
  const H = rows.length * rowH + 40;
  const X = (share: number) => lx + (rx - lx) * share;
  return (
    <figure style={{ margin: 'var(--s5) 0 0' }}>
      <p className="label">Fig · answers passed per dataset, before → after</p>
      <svg className="dia" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Per-dataset answers passed before and after the round, as a dumbbell chart">
        <title>Answers per dataset, before and after</title>
        {[0, 0.25, 0.5, 0.75, 1].map((g) => (
          <g key={g}>
            <line className="ax" x1={X(g)} x2={X(g)} y1={20} y2={H - 10} />
            <text className="tx k" x={X(g)} y={14} textAnchor="middle">
              {g * 100}%
            </text>
          </g>
        ))}
        {rows.map(([ds, t], i) => {
          const yy = 34 + i * rowH;
          const b = X(t.before / t.n);
          const a = X(t.after / t.n);
          const up = t.after > t.before;
          const down = t.after < t.before;
          return (
            <g key={ds}>
              <title>
                {ds}: {t.before}/{t.n} → {t.after}/{t.n}
              </title>
              <text className="tx" x={lx - 12} y={yy + 5} textAnchor="end">
                {ds}
              </text>
              <line className="ax" x1={b} x2={a} y1={yy} y2={yy} style={{ stroke: up ? 'var(--accent)' : down ? 'var(--amber)' : undefined, strokeWidth: 3 }} />
              <circle cx={b} cy={yy} r={6} fill="var(--panel)" stroke="var(--ink-2)" strokeWidth={2} />
              <circle cx={a} cy={yy} r={6} fill={up ? 'var(--accent)' : down ? 'var(--amber)' : 'var(--ink-2)'} />
              <text className="tx k" x={rx + 14} y={yy + 5}>
                {t.before} → {t.after} / {t.n}
              </text>
            </g>
          );
        })}
      </svg>
      <p className="small">
        Open dot: the source run; filled dot: the outcome run; <span className="v-ok">accent</span> a dataset that gained, <span className="v-warn">amber</span> one that lost, grey unchanged.
      </p>
    </figure>
  );
}

// ── helpers ────────────────────────────────────────────────────────────────

function sum(e: { read: number; train: number; held: number; none: number }): number {
  return e.read + e.train + e.held + e.none;
}

function groupBy<T>(xs: T[], key: (x: T) => string): Record<string, T[]> {
  const out: Record<string, T[]> = {};
  for (const x of xs) (out[key(x)] ??= []).push(x);
  return out;
}
