import type { KeyboardEvent } from 'react';
import { Link, Outlet, useNavigate, useParams } from 'react-router-dom';
import { type Attempt, type Change, COMPONENTS, type Component, type OptimiseSessionRec, type QuestionChange, type Rate as RateT, type RoundDetail, type RoundSummary, type Rounds, type Side, type Stages, type Tally, type TallyCore, type VersionNode, fmtUsd, useGet } from '../lib/api';
import { GoldDiff } from '../lib/golddiff';
import { Mark, rate } from '../lib/scorecard';
import { Loading } from '../lib/ui';
import { agentPath, goldenPath, optimisePath, questionPath, runPath, trialPath, useLens } from '../lib/url';

/**
 * Optimisation rounds, explored like runs (plan s06, redesigned in s08). A round read a scored
 * run (the diagnostic), wrote a new version (the proposal), and that version's run is its
 * outcome. The page leads with the loop itself, seven stages with the round's own counts
 * (D37 A), then the versions over time with the statement first (SQL of the questions with a
 * golden, the round's target), then the rounds. A round opens in place (`/optimise/<version>`):
 * where each statement broke (the ledger's component matrix), one card per optimiser session,
 * and the outcome with held-out first.
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
const r = (x: RateT | null | undefined) => (x ? `${x.passed}/${x.n}` : '—');
const onKey = (go: () => void) => (e: KeyboardEvent) => {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    go();
  }
};

// ── the list ───────────────────────────────────────────────────────────────

export function Optimise() {
  const { version } = useParams();
  const { data, error } = useGet<Rounds>('/api/optimise');
  if (!data) return <Loading error={error} />;
  const rounds = data.rounds;
  const last = rounds[rounds.length - 1];
  const focus = rounds.find((x) => x.version === version) ?? last;
  const sqlB = last?.before?.totals.sql;
  const sqlA = last?.after?.totals.sql;
  const hoB = last?.before?.by_split?.heldout?.sql;
  const hoA = last?.after?.by_split?.heldout?.sql;
  return (
    <>
      <p className="label">
        optimise · {rounds.length} round{rounds.length === 1 ? '' : 's'} · {data.versions.length} versions · champion <code>{data.champion}</code>
      </p>
      <h1>
        {last && sqlB ? (
          sqlA && last.outcome_run ? (
            <>
              The newest round wrote {last.version}: SQL {sqlB.passed} → <em>{sqlA.passed} of {sqlA.n}</em>, held out {r(hoB)} → {r(hoA)}; answers {last.changes.before} → {last.changes.after} of {last.changes.n}
            </>
          ) : (
            <>
              The newest round wrote <em>{last.version}</em>, not yet run; its source scored SQL {r(sqlB)} and answers {last.changes.before}/{last.changes.n}
            </>
          )
        ) : (
          <>No optimisation round has run yet</>
        )}
      </h1>
      <p className="lead">
        A round turns one scored run into the next version. The goal is the statement: SQL passes when the agent's statement, re-run, returns the golden's rows, and the answer follows. Click a stage below to see what it does and what this round's numbers were there.
      </p>
      {focus?.stages && <LoopFig round={focus} />}
      {data.versions.length > 0 && <RoundsChart nodes={data.versions} rounds={rounds} champion={data.champion} open={version ?? null} />}
      <Outlet />
      <h2>
        Every round — {rounds.length}, {fmtUsd(rounds.reduce((s, x) => s + (x.cost_usd ?? 0), 0), 2)} of optimiser time
      </h2>
      {rounds.length === 0 ? (
        <p className="empty">
          No round yet: <code>dab diagnose &lt;run&gt; --ledger</code>, then <code>dab optimise &lt;run&gt; --into &lt;version&gt;</code> writes one, and <code>dab eval --agent &lt;version&gt; --split all</code> gives it an outcome.
        </p>
      ) : (
        <RoundsTable rounds={rounds} open={version ?? null} />
      )}
    </>
  );
}

// ── Fig · the loop (D37 A) ─────────────────────────────────────────────────

type StageDef = { key: string; title: string; sub: (s: Stages) => string; edge: (s: Stages) => string; tone: '' | 'hi' | 'gold' | 'in'; body: (s: Stages, rd: RoundSummary) => { lead: string; facts: string[]; next?: string; files: string } };

const STAGES: StageDef[] = [
  {
    key: 'run',
    title: '1 · source run',
    sub: (s) => `${s.run.agent ?? '—'} · ${s.run.trials} trials`,
    edge: (s) => `SQL ${r(s.run.totals?.sql)}`,
    tone: '',
    body: (s) => ({
      lead: `The version being improved answers all 54 questions once. Each trial ends with submit_answer(sql, mode, …): the harness re-runs the statement as the read-only role and keeps its rows; the answer goes to the question's validator.`,
      facts: [s.run.agent ?? '—', `answers ${r(s.run.totals?.answer)}`, `SQL ${r(s.run.totals?.sql)}`, `decision ${r(s.run.totals?.decision)}`, fmtUsd(s.run.cost_usd, 2)],
      files: 'dab eval · agent/session.py · runs/<run>/results.jsonl',
    }),
  },
  {
    key: 'diagnose',
    title: '2 · diagnose',
    sub: (s) => (s.diagnose.ledger ? 'scorecard · ledger' : 'scorecard'),
    edge: (s) => `${s.diagnose.sql_fails} SQL fails`,
    tone: '',
    body: (s) => {
      const breaks = COMPONENTS.filter((c) => s.diagnose.breaks[c]).map((c) => `${c} ${s.diagnose.breaks[c]}`);
      return {
        lead: s.diagnose.ledger
          ? 'Every question is scored three ways (answer, SQL, decision). For every statement whose rows differ from the golden\'s, the reader writes both statements as seven steps in words and names the first step where the agent\'s goes a different way.'
          : 'Every question is scored three ways (answer, SQL, decision); a failure gets a category from a sqlglot structure diff. This run has no ledger, so it does not say which step of the statement broke.',
        facts: [`${s.diagnose.goldened} with a golden`, `${s.diagnose.sql_fails} SQL fails`, ...(breaks.length ? [`breaks at: ${breaks.join(', ')}`] : [])],
        next: s.diagnose.ledger ? undefined : 'dab diagnose <run> --ledger (s08)',
        files: 'dab diagnose · eval/scorecard.py · eval/ledger.py · runs/<run>/scorecard.json, ledger.json',
      };
    },
  },
  {
    key: 'split',
    title: '3 · split',
    sub: (s) => `${s.split.sizes?.train ?? '—'} train · ${s.split.sizes?.heldout ?? '—'} held out`,
    edge: (s) => `${s.split.read} read`,
    tone: 'in',
    body: (s) => ({
      lead: 'Only failed training questions go on to the optimiser. The held-out questions are never shown, so they test whether what it writes generalises; the questions without a golden stay outside the loop. The split is seeded and fixed, so every round is measured on the same questions.',
      facts: [`${s.split.sizes?.train ?? '—'} train`, `${s.split.sizes?.heldout ?? '—'} held out`, `${s.split.read} failed train questions read`, `held-out SQL before: ${r(s.split.heldout_sql)}`],
      files: 'data/splits/train.json · heldout.json',
    }),
  },
  {
    key: 'sessions',
    title: '4 · sessions',
    sub: (s) => [s.sessions.component ? `${s.sessions.component} steps` : '', s.sessions.dataset ? `${s.sessions.dataset} datasets` : '', s.sessions.system ? `${s.sessions.system} pass` : ''].filter(Boolean).join(' + '),
    edge: (s) => `${s.guard.writes} writes`,
    tone: 'hi',
    body: (s) => ({
      lead: s.sessions.component
        ? 'Isolated optimiser sessions write prompt text. A component session reads every failed training question whose statement breaks at one step, across all datasets, and writes that step\'s section of the SQL playbook; a dataset session writes facts about one dataset\'s data. Each can check a claim with read-only SQL before it writes.'
        : 'Isolated optimiser sessions write prompt text: one per dataset with failed training questions writes that dataset\'s notes, then one pass may move a recurring lesson into system.md.',
      facts: [`${s.sessions.component} component`, `${s.sessions.dataset} dataset`, `${s.sessions.system} system pass`, s.sessions.model ?? '—', fmtUsd(s.sessions.cost_usd, 2)],
      files: 'dab optimise · agent/optimise.py · agents/optimiser/*.md · runs/<run>/optimise/<version>/',
    }),
  },
  {
    key: 'guard',
    title: '5 · guard',
    sub: (s) => `${s.guard.refused} refused · ${s.guard.dropped} dropped`,
    edge: (s) => `${s.guard.accepted} accepted`,
    tone: 'gold',
    body: (s) => ({
      lead: 'Every write is checked before it exists: no run of 8 words from any question, no gold value written literally, no run of 6 tokens from any golden statement, and a length cap. A refusal names the problem and the session tries again; a second leak refusal drops the write.',
      facts: [`${s.guard.writes} writes`, `${s.guard.refused} refused`, `${s.guard.leaks} leaks caught`, `${s.guard.too_long} too long`, `${s.guard.accepted} accepted`, `${s.guard.dropped} dropped`, ...(s.guard.caps ? [`caps: notes ${s.guard.caps.notes}${s.guard.caps.section ? `, section ${s.guard.caps.section}` : ''}, system.md ${s.guard.caps.system_md}`] : [])],
      files: 'eval/guards.py',
    }),
  },
  {
    key: 'version',
    title: `6 · new version`,
    sub: (s) => [s.version.sections ? `${s.version.sections} sections` : '', `${s.version.notes} notes`].filter(Boolean).join(' + '),
    edge: () => '54 trials',
    tone: 'hi',
    body: (s) => ({
      lead: `${s.version.name} is a copy of its parent with the accepted text: ${s.version.sections ? 'the playbook sections in system.md, ' : ''}the dataset notes, and agent.yaml naming its parent${s.version.plan_first ? ', with plan: true so submit_answer asks for the seven-step plan' : ''}. Its fingerprint covers every prompt file, and the prompt is registered in MLflow.`,
      facts: [s.version.name, `${s.version.sections} playbook sections`, `${s.version.notes} dataset notes`, `system.md ${s.version.system_md_chars ?? '—'} chars`, ...(s.version.plan_first ? ['plan first'] : []), `fingerprint ${s.version.fingerprint ?? '—'}`, ...(s.version.prompt_version ? [`MLflow prompt v${s.version.prompt_version}`] : [])],
      files: `agents/${s.version.name}/ · tracking/prompts.py`,
    }),
  },
  {
    key: 'outcome',
    title: '7 · outcome',
    sub: (s) => (s.outcome.totals ? `SQL ${r(s.outcome.totals.sql)}` : 'not run yet'),
    edge: () => '',
    tone: '',
    body: (s) => ({
      lead: 'The new version answers the same 54, diagnosed the same way. dab promote then picks the champion among every version\'s newest complete run: the most SQL passed, answers breaking a tie (D36). This run is the next round\'s source.',
      facts: s.outcome.totals ? [`answers ${r(s.outcome.totals.answer)}`, `SQL ${r(s.outcome.totals.sql)}`, `held-out SQL ${r(s.outcome.heldout_sql)}`, s.outcome.promoted_at ? `promoted ${day(s.outcome.promoted_at)}` : 'not promoted'] : ['not run yet'],
      next: s.outcome.totals ? undefined : `dab eval --agent ${s.version.name} --split all`,
      files: 'eval/promote.py · agents/promotions.jsonl · eval/rounds.py',
    }),
  },
];

function LoopFig({ round }: { round: RoundSummary }) {
  const [sp, setLens] = useLens();
  const s = round.stages as Stages;
  const cur = Math.min(STAGES.length - 1, Math.max(0, Number(sp.get('stage') ?? 1) - 1));
  const go = (i: number) => setLens({ stage: String(((i + STAGES.length) % STAGES.length) + 1) });
  const W = 1160;
  const nw = 140;
  const gap = (W - 48 - nw * STAGES.length) / (STAGES.length - 1);
  const X = (i: number) => 24 + i * (nw + gap);
  const st = STAGES[cur];
  const b = st.body(s, round);
  return (
    <figure>
      <p className="label">
        Fig · how a round works · round {round.parent} → {round.version} · click a stage
      </p>
      <svg className="dia graph loop" viewBox={`0 0 ${W} 200`} role="img" aria-label="The optimisation loop as seven clickable stages, with this round's counts on the edges between them">
        <title>The optimisation loop, with this round's numbers</title>
        <defs>
          <marker id="larr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" fill="currentColor" />
          </marker>
        </defs>
        {STAGES.map((d, i) => (
          <g key={d.key}>
            {i < STAGES.length - 1 && (
              <>
                <path className="ed" d={`M${X(i) + nw},72 L${X(i + 1) - 2},72`} style={{ markerEnd: 'url(#larr)' }} />
                <text className="tx k" x={X(i) + nw + gap / 2} y={34} textAnchor="middle">
                  {d.edge(s)}
                </text>
              </>
            )}
            <g className={`pick ${cur === i ? 'on' : ''}`} role="button" tabIndex={0} aria-label={`stage ${i + 1}: ${d.title}`} aria-pressed={cur === i} onClick={() => go(i)} onKeyDown={onKey(() => go(i))}>
              <title>
                {d.title}: {d.sub(s)}
              </title>
              <rect className={`nd ${d.tone}`} x={X(i)} y={42} width={nw} height={60} rx={6} />
              <text className="tx" x={X(i) + nw / 2} y={67} textAnchor="middle">
                {d.title}
              </text>
              <text className="tx s" x={X(i) + nw / 2} y={87} textAnchor="middle">
                {d.sub(s)}
              </text>
            </g>
          </g>
        ))}
        <path className="ed dash" d={`M${X(6) + nw / 2},102 L${X(6) + nw / 2},148 L${X(0) + nw / 2},148 L${X(0) + nw / 2},106`} style={{ markerEnd: 'url(#larr)' }} />
        <text className="tx k" x={W / 2} y={170} textAnchor="middle">
          the outcome run is the next round's source run
        </text>
      </svg>
      <div className="stage-nav" role="group" aria-label="step through the round">
        <button type="button" className="tog" onClick={() => go(cur - 1)}>
          ◀ back
        </button>
        <button type="button" className="btn" onClick={() => go(cur + 1)}>
          next stage ▶
        </button>
        <span className="small muted">
          stage {cur + 1} of {STAGES.length}
        </span>
      </div>
      <div className="stage" aria-live="polite">
        <p className="label">
          stage {cur + 1} · round {round.parent} → {round.version}
        </p>
        <h3>{st.title}</h3>
        <p>{b.lead}</p>
        <div className="chips">
          {b.facts.map((f) => (
            <span key={f} className="chip ok">
              {f}
            </span>
          ))}
          {b.next && (
            <span className="chip no">
              next: <code>{b.next}</code>
            </span>
          )}
        </div>
        <p className="small">
          <span className="label">files</span> <code>{b.files}</code>
        </p>
      </div>
      <figcaption>
        Accent: what the round wrote; amber: the step that reads the goldens. Every count is this round's, from <code>agents/{round.version}/optimise.json</code> and the two runs' <code>scorecard.json</code>; pick another round below to redraw it.
      </figcaption>
    </figure>
  );
}

// ── Fig · the versions over time, the statement first ───────────────────────

function RoundsChart({ nodes, rounds, champion, open }: { nodes: VersionNode[]; rounds: RoundSummary[]; champion: string; open: string | null }) {
  const nav = useNavigate();
  const order = [...nodes].sort((a, b) => (a.started_at ?? '9').localeCompare(b.started_at ?? '9'));
  const byVersion = new Map(rounds.map((x) => [x.version, x]));
  const W = 1000;
  const H = 300;
  const lx = 64;
  const rx = W - 30;
  const top = 36;
  const bot = 220;
  const gap = order.length > 1 ? (rx - lx - 80) / (order.length - 1) : 0;
  const X = (i: number) => lx + 40 + i * gap;
  const Y = (share: number) => bot - (bot - top) * share;
  const idx = new Map(order.map((n, i) => [n.version, i]));
  const share = (x: RateT | null | undefined) => (x && x.n ? x.passed / x.n : null);
  const ans = order.map((n) => (n.passed != null && n.scored ? n.passed / n.scored : null));
  const sql = order.map((n) => share(n.sql));
  const edges = order.flatMap((n) => {
    const from = n.parent ?? n.measured_against;
    if (!from || !idx.has(from)) return [];
    const f = order[idx.get(from) as number];
    const kind = n.parent ? 'round' : f.model && n.model && f.model !== n.model ? 'model' : 'hand';
    return [{ from: idx.get(from) as number, to: idx.get(n.version) as number, kind, label: kind === 'round' ? 'round' : kind === 'model' ? `${f.model} → ${n.model}` : 'hand-built' }];
  });
  return (
    <figure>
      <p className="label">Fig · every version in order: SQL passed (filled) and answers passed (open), each on its own denominator</p>
      <svg className="dia" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Every agent version in order, with the share of SQL passed and of answers passed on its newest complete run; a round is a solid edge, a model switch or hand-built version a dashed one">
        <title>SQL and answers per version</title>
        {[0, 0.25, 0.5, 0.75, 1].map((g) => (
          <g key={g}>
            <line className="ax" x1={lx} x2={rx} y1={Y(g)} y2={Y(g)} style={{ strokeDasharray: g ? '2 4' : undefined }} />
            <text className="tx k" x={lx - 8} y={Y(g) + 4} textAnchor="end">
              {g * 100}%
            </text>
          </g>
        ))}
        {edges.map((e) => {
          const x1 = X(e.from);
          const x2 = X(e.to);
          const mid = (x1 + x2) / 2;
          return (
            <g key={`${e.from}-${e.to}`}>
              <title>
                {order[e.from].version} → {order[e.to].version}: {e.label}
              </title>
              <line x1={x1} x2={x2} y1={bot + 22} y2={bot + 22} stroke="currentColor" style={{ stroke: e.kind === 'round' ? 'var(--accent)' : 'var(--line-3)', strokeDasharray: e.kind === 'round' ? undefined : '4 3', strokeWidth: 2 }} />
              <text className="tx k" x={mid} y={bot + 38} textAnchor="middle">
                {e.label}
              </text>
            </g>
          );
        })}
        <polyline fill="none" style={{ stroke: 'var(--ink-2)', strokeDasharray: '5 4', strokeWidth: 1.5 }} points={ans.map((v, i) => (v == null ? '' : `${X(i)},${Y(v)}`)).filter(Boolean).join(' ')} />
        <polyline fill="none" style={{ stroke: 'var(--accent)', strokeWidth: 2.5 }} points={sql.map((v, i) => (v == null ? '' : `${X(i)},${Y(v)}`)).filter(Boolean).join(' ')} />
        {order.map((n, i) => {
          const rd = byVersion.get(n.version);
          const go = () => (rd ? nav(optimisePath(n.version)) : nav(agentPath(n.version)));
          const ho = n.heldout?.sql;
          return (
            <g key={n.version} className="pick" role="button" tabIndex={0} aria-label={`${n.version}: SQL ${r(n.sql)}, answers ${n.passed ?? '—'} of ${n.scored ?? '—'}`} onClick={go} onKeyDown={onKey(go)}>
              <title>
                {n.version} ({n.model ?? '—'}): SQL {r(n.sql)} · held-out SQL {r(ho)} · answers {n.passed ?? '—'}/{n.scored ?? '—'}
                {rd ? ' · open its round' : ' · open the agent'}
              </title>
              {ans[i] != null && (
                <>
                  <circle cx={X(i)} cy={Y(ans[i] as number)} r={6} style={{ fill: 'var(--panel)', stroke: 'var(--ink-2)', strokeWidth: 2 }} />
                  <text className="tx k" x={X(i)} y={Y(ans[i] as number) - 13} textAnchor="middle">
                    {n.passed}/{n.scored}
                  </text>
                </>
              )}
              {sql[i] != null && (
                <>
                  <circle cx={X(i)} cy={Y(sql[i] as number)} r={7} style={{ fill: 'var(--accent)' }} />
                  {/* centred under the point on two lines, so neighbours a question apart never collide */}
                  <text className="tx k" x={X(i)} y={Y(sql[i] as number) + 24} textAnchor="middle" style={{ fill: 'var(--ink)' }}>
                    SQL {r(n.sql)}
                  </text>
                  {ho && (
                    <text className="tx k" x={X(i)} y={Y(sql[i] as number) + 40} textAnchor="middle">
                      ho {r(ho)}
                    </text>
                  )}
                </>
              )}
              <text className="tx" x={X(i)} y={bot + 60} textAnchor="middle" style={open === n.version ? { fontWeight: 700 } : undefined}>
                {n.version}
                {n.version === champion ? ' · champion' : ''}
              </text>
              <text className="tx s" x={X(i)} y={bot + 76} textAnchor="middle">
                {n.model ?? ''}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption>
        <b>The filled line is the target</b>: SQL passed of the questions with a golden; the open dots are answers passed of the 54, the leaderboard's number; <code>ho</code> is held-out SQL. A solid accent edge is an optimisation round, a dashed one a hand-built version or a model switch. Click a version to open its round (or its agent page). Source: each version's newest complete full-split run.
      </figcaption>
    </figure>
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
            <th className="num">SQL before → after</th>
            <th className="num">Held-out SQL</th>
            <th className="num">Answers</th>
            <th>Wrote</th>
            <th className="num">Cost</th>
            <th>Promoted</th>
          </tr>
        </thead>
        <tbody>
          {[...rounds].reverse().map((x) => {
            const sb = x.before?.totals.sql;
            const sa = x.after?.totals.sql;
            const hb = x.before?.by_split?.heldout?.sql;
            const ha = x.after?.by_split?.heldout?.sql;
            return (
              <tr key={x.version} className={`pickrow ${open === x.version ? 'cur' : ''}`} onClick={() => nav(optimisePath(x.version))}>
                <td className="sub">
                  <Link to={optimisePath(x.version)} onClick={(e) => e.stopPropagation()}>
                    {x.parent} → {x.version}
                  </Link>
                  <span className="path">
                    {day(x.started_at)} · {x.optimiser?.model} @ {x.optimiser?.effort}
                  </span>
                </td>
                <td className="small nw">
                  <Link to={runPath(x.source_run)} onClick={(e) => e.stopPropagation()} title={x.source_run}>
                    {x.parent}'s run
                  </Link>
                  <span className="path">{x.source_run.slice(0, 16)}</span>
                </td>
                <td className="num">
                  {r(sb)} → {x.outcome_run ? r(sa) : 'not run yet'}
                </td>
                <td className="num">
                  {r(hb)} → {x.outcome_run ? r(ha) : '—'}
                </td>
                <td className="num">
                  {x.changes.before}/{x.changes.n} → {x.outcome_run ? `${x.changes.after}/${x.changes.n}` : '—'}
                </td>
                <td className="small nw">
                  {x.sections_written ? `${x.sections_written} sections + ` : ''}
                  {x.notes_written} notes{x.system_md_changed && !x.sections_written ? ' + system.md' : ''}
                  <span className="path">{x.refusals} refusals</span>
                </td>
                <td className="num">{fmtUsd(x.cost_usd, 2)}</td>
                <td>{x.promoted_at ? <span className="chip ok">champion {day(x.promoted_at)}</span> : <span className="small muted">no</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
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
  const st = s.stages;
  const o = data.outcome;
  const oSql = o?.all.sql;
  const hoSql = o?.by_split.heldout?.sql;
  const breaks = st ? COMPONENTS.filter((c) => st.diagnose.breaks[c]).map((c) => `${c} ${st.diagnose.breaks[c]}`) : [];
  const steps: { key: View; n: string; title: string; body: string }[] = [
    {
      key: 'diagnostic',
      n: '1',
      title: 'Diagnostic',
      body: `${rec.challenger_of}'s run: SQL ${rate(data.diagnostic.totals?.sql)} · answers ${rate(data.diagnostic.totals?.answer)}; ${st?.split.read ?? 0} failed train questions read` + (breaks.length ? `; first breaks: ${breaks.join(', ')}` : ''),
    },
    {
      key: 'proposal',
      n: '2',
      title: 'Proposal',
      body: st ? `${st.version.sections ? `${st.version.sections} playbook sections + ` : ''}${st.version.notes} dataset notes${st.version.plan_first ? ', plan first' : ''}; ${st.guard.writes} writes, ${st.guard.refused} refused (${st.guard.leaks} leaks), ${st.guard.accepted} accepted; ${fmtUsd(rec.cost_usd, 2)}` : '',
    },
    {
      key: 'outcome',
      n: '3',
      title: 'Outcome',
      body: o && oSql ? `SQL ${oSql.before} → ${oSql.after} of ${oSql.n}, held out ${hoSql ? `${hoSql.before} → ${hoSql.after} of ${hoSql.n}` : '—'}; answers ${o.all.before} → ${o.all.after} of ${o.all.n}` : `${version} has no complete run yet`,
    },
  ];
  return (
    <section className="card round-open" aria-label={`optimisation round ${version}`}>
      <p className="label">
        round · {rec.challenger_of} → {version} · {day(rec.started_at)} · {rec.optimiser.model} @ {rec.optimiser.effort} · split {rec.split.train} train / {rec.split.heldout} held out ·{' '}
        <Link to={agentPath(version)}>the agent</Link> · <Link to={optimisePath()}>close</Link>
      </p>
      <h2>
        {version}:{' '}
        {o && oSql ? `SQL ${signed(oSql.after - oSql.before)} of ${oSql.n} (${oSql.before} → ${oSql.after})${hoSql ? `, held out ${signed(hoSql.after - hoSql.before)} of ${hoSql.n}` : ''}; answers ${signed(o.all.after - o.all.before)} of ${o.all.n}` : 'written, not yet run'}
        {s.promoted_at ? `; champion since ${day(s.promoted_at)}` : ''}
      </h2>
      <p className="small">{rec.method ?? s.method}</p>
      <div className="steps3" role="tablist" aria-label="the round's three steps">
        {steps.map((x, i) => (
          <button key={x.key} type="button" role="tab" aria-selected={view === x.key} className={`step ${view === x.key ? 'on' : ''}`} onClick={() => setLens({ view: x.key === 'diagnostic' ? null : x.key, change: null, cell: null })}>
            <span className="label">
              {x.n} · {x.title}
            </span>
            <span className="small">{x.body}</span>
            {i < steps.length - 1 && <span className="arrow" aria-hidden="true">→</span>}
          </button>
        ))}
      </div>
      {view === 'diagnostic' && <Diagnostic d={data} />}
      {view === 'proposal' && <Proposal d={data} />}
      {view === 'outcome' && (o ? <Outcome d={data} /> : <p className="empty">Run it: <code>dab eval --agent {version} --split all</code>, then <code>dab diagnose &lt;run&gt; --ledger</code>. The outcome is its newest complete full-split run.</p>)}
    </section>
  );
}

const isLeak = (p: string) => !/characters; the limit is/.test(p);

// ── 1 · diagnostic: where each statement broke ─────────────────────────────

function Diagnostic({ d }: { d: RoundDetail }) {
  const src = d.diagnostic.run_id;
  const hasLedger = d.questions.some((q) => q.before?.verdicts);
  return (
    <>
      <p>
        What the optimiser was given: the scorecard of <Link to={runPath(src)} className="mono">{src}</Link> (SQL {rate(d.diagnostic.totals?.sql)} · answers {rate(d.diagnostic.totals?.answer)} · decision {rate(d.diagnostic.totals?.decision)}). Only failed <i>training</i> questions were read; held-out and no-golden questions were never shown.
      </p>
      {hasLedger ? <ComponentMatrix d={d} /> : <CategoryBars d={d} />}
    </>
  );
}

function ComponentMatrix({ d }: { d: RoundDetail }) {
  const [sp, setLens] = useLens();
  const rows = d.questions.filter((q) => q.before && q.before.sql === false).sort((a, b) => a.dataset.localeCompare(b.dataset) || Number(a.query_id.split('/')[1]) - Number(b.query_id.split('/')[1]));
  const [openQ, openC] = (sp.get('cell') ?? '').split(':') as [string, Component | undefined];
  const cw = 72;
  const lx = 250;
  const rowH = 22;
  const W = lx + COMPONENTS.length * cw + 250;
  const H = 34 + rows.length * rowH + 30;
  const firsts: Partial<Record<Component, number>> = {};
  for (const q of rows) if (q.before?.breaks_at) firsts[q.before.breaks_at] = (firsts[q.before.breaks_at] ?? 0) + 1;
  const sel = rows.find((q) => q.query_id === openQ);
  const where = (q: QuestionChange) => (q.read ? 'read' : q.split === 'heldout' ? 'held out' : q.split ?? '—');
  return (
    <figure>
      <p className="label">
        Fig · the {rows.length} statements whose rows differ from the golden's, by step · the outlined cell is where each first breaks · click a cell
      </p>
      <div className="figscroll">
        <svg className="dia" viewBox={`0 0 ${W} ${H}`} style={{ minWidth: 720 }} role="img" aria-label="Component matrix: each failed statement against the seven steps of a statement; amber where the agent's step differs from the golden's, the first break outlined">
          <title>Where each statement breaks</title>
          {COMPONENTS.map((c, j) => (
            <text key={c} className="tx k" x={lx + j * cw + cw / 2 - 4} y={22} textAnchor="middle">
              {c}
            </text>
          ))}
          <text className="tx k" x={lx + COMPONENTS.length * cw + 8} y={22}>
            answer · after the round (SQL)
          </text>
          {rows.map((q, i) => {
            const y = 34 + i * rowH;
            const b = q.before as Side;
            return (
              <g key={q.query_id}>
                <text className="tx s" x={lx - 12} y={y + 13} textAnchor="end">
                  {q.query_id} · {where(q)}
                </text>
                {COMPONENTS.map((c, j) => {
                  const v = b.verdicts?.[c];
                  const first = b.breaks_at === c;
                  const on = openQ === q.query_id && openC === c;
                  const go = () => setLens({ cell: on ? null : `${q.query_id}:${c}` });
                  return (
                    <g key={c} className="pick cellpick" role="button" tabIndex={0} aria-label={`${q.query_id} ${c}: ${v ?? 'not read'}${first ? ', the first break' : ''}`} onClick={go} onKeyDown={onKey(go)}>
                      <title>
                        {q.query_id} · {c}: {v ?? 'no ledger'}
                        {first ? ' · the first break' : ''}
                      </title>
                      <rect className={`cell ${v ?? 'blind'} ${first ? 'first' : ''} ${on ? 'on' : ''}`} x={lx + j * cw} y={y} width={cw - 8} height={rowH - 6} rx={2} />
                    </g>
                  );
                })}
                <text className="tx k" x={lx + COMPONENTS.length * cw + 8} y={y + 13}>
                  {b.answer ? 'pass' : 'fail'} · {q.after ? `SQL ${q.after.sql ? 'pass' : 'fail'}${q.sql_change === 'improved' ? ' ▲' : q.sql_change === 'regressed' ? ' ▼' : ''}` : 'not run'}
                </text>
              </g>
            );
          })}
          <line className="ax" x1={lx} x2={lx + COMPONENTS.length * cw - 8} y1={H - 26} y2={H - 26} />
          <text className="tx s" x={lx - 12} y={H - 10} textAnchor="end">
            first breaks
          </text>
          {COMPONENTS.map((c, j) => (
            <text key={c} className="tx k strong" x={lx + j * cw + cw / 2 - 4} y={H - 10} textAnchor="middle">
              {firsts[c] ?? 0}
            </text>
          ))}
        </svg>
      </div>
      <figcaption>
        <span className="lgd"><i className="sw diff" /> the agent's step differs</span> <span className="lgd"><i className="sw same" /> same in effect</span> <span className="lgd"><i className="sw blind" /> not read</span> · outlined: the first step that changes the result. <code>read</code>: a failed train question the optimiser saw; <code>held out</code>: never shown. Source: the reader's ledger, <code>runs/{d.diagnostic.run_id}/ledger.json</code>.
      </figcaption>
      {sel && openC && <CellPanel q={sel} c={openC} run={d.diagnostic.run_id} after={d.summary.outcome_run} what={d.components?.find((x) => x.name === openC)?.what ?? ''} />}
    </figure>
  );
}

function CellPanel({ q, c, run, after, what }: { q: QuestionChange; c: Component; run: string; after: string | null; what: string }) {
  const b = q.before as Side;
  const v = b.verdicts?.[c] ?? 'not read';
  return (
    <div className="stage">
      <p className="label">
        {q.query_id} · {c} · {v}
        {b.breaks_at === c ? ' · the first break' : ''}
      </p>
      <p className="small">{q.question}</p>
      <div className="tw" style={{ boxShadow: 'none' }}>
        <table className="lines">
          <caption>
            {c}: {what}
          </caption>
          <tbody>
            <tr>
              <td className="sub">golden</td>
              <td>{b.golden_lines?.[c] ?? '—'}</td>
            </tr>
            <tr>
              <td className="sub">agent</td>
              <td>{b.agent_lines?.[c] ?? '—'}</td>
            </tr>
          </tbody>
        </table>
      </div>
      {b.why && (
        <p className="small">
          <b>Where it broke ({b.breaks_at ?? '—'}):</b> {b.why}
        </p>
      )}
      <p className="small">
        <Link to={trialPath(run, `${q.query_id}/t1`)}>the trial</Link> · <Link to={goldenPath(q.query_id)}>the golden</Link>
        {after && (
          <>
            {' '}
            · <Link to={trialPath(after, `${q.query_id}/t1`)}>after the round</Link> ({q.after?.sql ? 'SQL passes' : 'SQL still fails'})
          </>
        )}
      </p>
    </div>
  );
}

/** A run without a ledger: the failure categories, split into read, held out and no golden. */
function CategoryBars({ d }: { d: RoundDetail }) {
  const failed = d.questions.filter((q) => q.before && q.before.category !== 'solved');
  const cats = new Map<string, { read: number; train: number; held: number; none: number }>();
  for (const q of failed) {
    const c = q.before?.category || '—';
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
  return (
    <figure>
      <p className="label">Fig · every question the source run did not solve, by failure category (no ledger: run dab diagnose --ledger)</p>
      <svg className="dia" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Failure categories in the source run">
        <title>Failure categories in the source run</title>
        {rows.map(([c, e], i) => {
          const yy = 8 + i * rowH;
          const seg = [
            { k: 'read', v: e.read, cls: 'bar hi' },
            { k: 'train', v: e.train, cls: 'bar b' },
            { k: 'held', v: e.held, cls: 'bar ho' },
            { k: 'none', v: e.none, cls: 'bar' },
          ];
          let at = lx;
          return (
            <g key={c}>
              <text className="tx" x={lx - 10} y={yy + 18} textAnchor="end">
                {c}
              </text>
              {seg.map((sg) => {
                const w = (bw * sg.v) / max;
                const el = sg.v ? <rect key={sg.k} className={sg.cls} x={at} y={yy + 4} width={Math.max(0, w - 1)} height={rowH - 10} rx={2} /> : null;
                at += w;
                return el;
              })}
              <text className="tx k" x={at + 8} y={yy + 18}>
                {sum(e)}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption>Accent: failed training questions a session read; outlined: held out; grey: no golden.</figcaption>
    </figure>
  );
}

// ── 2 · proposal: one card per session ─────────────────────────────────────

function attemptsOf(s: OptimiseSessionRec): Attempt[] {
  if (s.attempts) return s.attempts;
  const out: Attempt[] = s.refusals.map((x) => ({ ok: false, chars: x.notes_chars ?? null, problems: x.problems }));
  if (s.notes != null) out.push({ ok: true, chars: s.notes.length, problems: [] });
  return out;
}
const kindOf = (s: OptimiseSessionRec) => s.kind ?? (s.scope === 'system.md' ? 'system' : 'dataset');

function Proposal({ d }: { d: RoundDetail }) {
  const rec = d.record;
  const version = rec.version;
  const sys = d.files.find((f) => f.name === 'system.md');
  const notes = d.files.filter((f) => f.name !== 'system.md');
  const byQ = new Map(d.questions.map((q) => [q.query_id, q]));
  const order = { component: 0, dataset: 1, system: 2 } as const;
  const sessions = [...rec.sessions].sort((a, b) => order[kindOf(a)] - order[kindOf(b)] || a.scope.localeCompare(b.scope));
  return (
    <>
      <p>
        {sessions.some((s) => kindOf(s) === 'component')
          ? `Isolated ${rec.optimiser.model} sessions: one per step at which training statements broke, reading those questions across every dataset and writing that step's section of the SQL playbook in system.md; one per dataset writing its notes. `
          : `One isolated ${rec.optimiser.model} session per dataset (tools: query_db to check a claim, write_notes to finish) and one cross-dataset pass over system.md. `}
        Every write is checked for question text, gold values written literally, copied golden SQL and length; a refusal goes back with its reasons, and a second <i>leak</i> refusal drops the write.
      </p>
      <div className="grid2 sessions">
        {sessions.map((s) => {
          const att = attemptsOf(s);
          const kind = kindOf(s);
          return (
            <article key={s.scope} className="card session">
              <p className="label">
                {kind === 'component' ? 'playbook section' : kind === 'system' ? 'cross-dataset pass' : 'dataset notes'} · {s.scope.replace('playbook:', '')} · {s.n_turns} turns · {fmtUsd(s.cost_usd, 3)}
                {s.budget ? ` · cap ${s.budget}` : ''}
              </p>
              <ol className="attempts">
                {att.map((a, i) => (
                  <li key={i}>
                    <span className="mono muted">attempt {i + 1}</span> {a.ok ? <span className="v-ok">accepted</span> : <span className="v-warn">refused</span>} · {a.chars ?? '—'} chars
                    {!a.ok && <span className="small"> · {[...new Set(a.problems.map((p) => (isLeak(p) ? p.split(':')[0] : 'too long')))].join(' · ')}</span>}
                  </li>
                ))}
                {s.error && <li className="v-warn">error: {s.error}</li>}
                {s.dropped && <li className="v-warn">dropped after a second leak</li>}
              </ol>
              {s.questions.length > 0 && (
                <div className="chips">
                  {s.questions.map((qid) => {
                    const q = byQ.get(qid);
                    const ch = q?.sql_change ?? q?.change;
                    return (
                      <Link key={qid} to={questionPath(qid)} className={`chip ${ch ? CHANGE_TONE[ch] : ''}`} title={q ? `${qid}: SQL ${q.before?.sql ? 'pass' : 'fail'} → ${q.after ? (q.after.sql ? 'pass' : 'fail') : 'not run'}` : qid}>
                        {qid}
                        {ch === 'improved' ? ' ▲' : ch === 'regressed' ? ' ▼' : ''}
                      </Link>
                    );
                  })}
                </div>
              )}
              {s.rationale && <p className="small">{s.rationale}</p>}
              {s.notes && (
                <details>
                  <summary>the text it wrote ({s.notes.length} chars)</summary>
                  <pre className="wrap-any">{s.notes}</pre>
                </details>
              )}
            </article>
          );
        })}
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

// ── 3 · outcome, held out first ────────────────────────────────────────────

type Metric = 'sql' | 'answer';

function Outcome({ d }: { d: RoundDetail }) {
  const o = d.outcome!;
  const s = d.summary;
  const [sp, setLens] = useLens();
  const metric = (sp.get('metric') as Metric) ?? 'sql';
  const filter = (sp.get('change') as Change | null) ?? null;
  const chg = (q: QuestionChange): Change => (metric === 'sql' ? q.sql_change ?? 'not scored' : q.change);
  const pick = (t: Tally): TallyCore | undefined => (metric === 'sql' ? t.sql : t);
  const shown = d.questions.filter((q) => !filter || chg(q) === filter);
  const all = pick(o.all);
  const splits: [string, string][] = [
    ['heldout', 'held out · never shown'],
    ['train', 'train · failures read'],
    ['no golden', 'no golden · answer only'],
  ];
  return (
    <>
      <p>
        <Link to={runPath(s.source_run)} className="mono">{s.source_run}</Link> ({d.record.challenger_of}) against <Link to={runPath(s.outcome_run!)} className="mono">{s.outcome_run}</Link> ({d.record.version}), question by question. The held-out line is the test of whether what the round wrote generalises.
      </p>
      <div className="filters" role="group" aria-label="the measure and the change">
        {(['sql', 'answer'] as Metric[]).map((m) => (
          <button key={m} type="button" className={`tog ${metric === m ? 'on' : ''}`} aria-pressed={metric === m} onClick={() => setLens({ metric: m === 'sql' ? null : m, change: null })}>
            {m === 'sql' ? 'SQL (the target)' : 'answers'}
          </button>
        ))}
        <span className="small muted">·</span>
        {all &&
          (['improved', 'regressed', 'held', 'still failing'] as Change[]).map((c) => (
            <button key={c} type="button" className={`tog ${filter === c ? 'on' : ''}`} aria-pressed={filter === c} onClick={() => setLens({ change: filter === c ? null : c })}>
              {CHANGE_LABEL[c]} {all[c]}
            </button>
          ))}
      </div>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>Questions</th>
              <th className="num">SQL before → after</th>
              <th className="num">Answers before → after</th>
              <th className="num">Improved</th>
              <th className="num">Regressed</th>
              <th className="num">Still failing</th>
            </tr>
          </thead>
          <tbody>
            {splits
              .filter(([k]) => o.by_split[k])
              .map(([k, label]) => (
                <SplitRow key={k} label={label} t={o.by_split[k]} metric={metric} strong={k === 'heldout'} />
              ))}
            <SplitRow label="all" t={o.all} metric={metric} />
          </tbody>
        </table>
      </div>
      <OutcomeGrid d={d} metric={metric} />
      <Dumbbell by={o.by_dataset} metric={metric} />
      {o.category_moves.some((m) => m.from !== m.to) && (
        <details style={{ marginTop: 'var(--s4)' }}>
          <summary>How failure categories moved ({o.category_moves.filter((m) => m.from !== m.to).reduce((n, m) => n + m.n, 0)} questions)</summary>
          <div className="tw">
            <table>
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
        </details>
      )}
      <h3 style={{ marginTop: 'var(--s6)' }}>
        {filter ? `${shown.length} question${shown.length === 1 ? '' : 's'} ${CHANGE_LABEL[filter]} on ${metric === 'sql' ? 'SQL' : 'the answer'}` : `Every question, ${shown.length}`}
      </h3>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>Question</th>
              <th>Split</th>
              <th>Before · {d.record.challenger_of}</th>
              <th>After · {d.record.version}</th>
              <th>SQL</th>
              <th>Answer</th>
              <th>Trials</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((q) => (
              <tr key={q.query_id} className={chg(q) === 'regressed' ? 'warnrow' : ''}>
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
                <td>{q.sql_change && q.sql_change !== 'not scored' ? <span className={`chip ${CHANGE_TONE[q.sql_change]}`}>{CHANGE_LABEL[q.sql_change]}</span> : <span className="small muted">—</span>}</td>
                <td>
                  <span className={`chip ${CHANGE_TONE[q.change]}`}>{CHANGE_LABEL[q.change]}</span>
                </td>
                <td className="small nw">
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

function SplitRow({ label, t, metric, strong = false }: { label: string; t: Tally; metric: Metric; strong?: boolean }) {
  const m = metric === 'sql' ? t.sql : t;
  const delta = (a: number, b: number) => <span className={b > a ? 'v-ok' : b < a ? 'v-warn' : 'muted'}>({signed(b - a)})</span>;
  return (
    <tr className={strong ? 'pro' : ''}>
      <td className="sub">{strong ? <b>{label}</b> : label}</td>
      <td className="num">
        {t.sql && t.sql.n ? (
          <>
            {t.sql.before} → {t.sql.after} / {t.sql.n} {delta(t.sql.before, t.sql.after)}
          </>
        ) : (
          '—'
        )}
      </td>
      <td className="num">
        {t.before} → {t.after} / {t.n} {delta(t.before, t.after)}
      </td>
      <td className="num">{m && m.n ? m.improved : '—'}</td>
      <td className="num">{m && m.n ? m.regressed : '—'}</td>
      <td className="num">{m && m.n ? m['still failing'] : '—'}</td>
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

/** Every question as a pair of cells, before over after, grouped by dataset, on the chosen measure. */
function OutcomeGrid({ d, metric }: { d: RoundDetail; metric: Metric }) {
  const nav = useNavigate();
  const s = d.summary;
  const byDs = Object.entries(groupBy(d.questions, (q) => q.dataset));
  const most = Math.max(...byDs.map(([, qs]) => qs.length));
  const lx = 170;
  const cw = 44;
  const W = Math.max(1000, lx + most * cw + 20);
  const rowH = 64;
  const H = byDs.length * rowH + 30;
  const v = (x: Side | null) => (x ? (metric === 'sql' ? x.sql : x.answer) : null);
  const cls = (x: boolean | null | undefined) => (x == null ? 'bar' : x ? 'bar hi' : 'bar pro');
  const ch = (q: QuestionChange) => (metric === 'sql' ? q.sql_change : q.change);
  return (
    <figure>
      <p className="label">Fig · every question, before (top) over after (bottom), by dataset · {metric === 'sql' ? 'SQL' : 'answers'}</p>
      <div className="figscroll">
        <svg className="dia" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Per-question outcome grid: each question as two cells, before and after the round; passed in accent, failed in amber, grey where there is no golden">
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
                  const c = ch(q);
                  return (
                    <g key={q.query_id} className="pt" style={{ cursor: 'pointer' }} onClick={() => nav(trialPath(s.outcome_run!, `${q.query_id}/t1`))}>
                      <title>
                        {q.query_id} ({q.split ?? '—'}): {c ? CHANGE_LABEL[c] : '—'} · before {q.before?.category} · after {q.after?.category}
                      </title>
                      <rect className={cls(v(q.before))} x={xx} y={yy} width={cw - 8} height={16} rx={2} />
                      <rect className={cls(v(q.after))} x={xx} y={yy + 18} width={cw - 8} height={16} rx={2} />
                      <text className="tx k" x={xx + (cw - 8) / 2} y={yy + 50} textAnchor="middle">
                        {c === 'improved' ? `▲${n}` : c === 'regressed' ? `▼${n}` : n}
                      </text>
                    </g>
                  );
                })}
              </g>
            );
          })}
        </svg>
      </div>
      <figcaption>
        Each pair is one question: the top cell is the source run, the bottom the outcome run; <span className="v-ok">accent</span> passed, <span className="v-warn">amber</span> failed{metric === 'sql' ? ', grey no golden' : ''}. Click for the trial after the round.
      </figcaption>
    </figure>
  );
}

/** Per dataset, the chosen measure before (open dot) and after (filled), on the dataset's own share. */
function Dumbbell({ by, metric }: { by: Record<string, Tally>; metric: Metric }) {
  const rows = Object.entries(by)
    .map(([ds, t]) => [ds, metric === 'sql' ? t.sql : t] as const)
    .filter((x): x is readonly [string, TallyCore] => !!x[1] && x[1].n > 0);
  const W = 1000;
  const lx = 190;
  const rx = W - 110;
  const rowH = 30;
  const H = rows.length * rowH + 40;
  const X = (share: number) => lx + (rx - lx) * share;
  return (
    <figure>
      <p className="label">Fig · {metric === 'sql' ? 'SQL' : 'answers'} passed per dataset, before → after</p>
      <svg className="dia" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Per-dataset share passed before and after the round, as a dumbbell chart">
        <title>Per dataset, before and after</title>
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
      <figcaption>
        Open dot: the source run; filled dot: the outcome run; <span className="v-ok">accent</span> a dataset that gained, <span className="v-warn">amber</span> one that lost, grey unchanged. {metric === 'sql' ? 'Over the questions with a golden.' : 'Over every question.'}
      </figcaption>
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
