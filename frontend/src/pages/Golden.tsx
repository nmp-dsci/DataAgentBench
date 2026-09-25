import { useEffect, useRef, useState } from 'react';
import { Link, Outlet, useLocation, useNavigate, useOutletContext, useParams } from 'react-router-dom';
import { type Board, type GoldMatch, type GoldenAttempt, type GoldenKind, type GoldenList, type GoldenOne, type ProposalBrief, type RunDetail, type RunSummary, type ToolCall, type Trace, type TrialRow, ROLE_LABEL, STYLE_LABEL, fmtInt, post, useGet } from '../lib/api';
import { Clip, Gold, Loading } from '../lib/ui';
import { GoldDiff } from '../lib/golddiff';
import { SqlVersus, StepsTable } from '../lib/scorecard';
import { SqlBlock, SqlEditor } from '../lib/sql';
import { apiTrialPath, datasetPath, goldenPath, questionPath, trialId, trialPath, useLens } from '../lib/url';

function Status({ g, kind }: { g: { passed: boolean | null; kind?: GoldenKind } | null; kind?: GoldenKind }) {
  if (!g) return <span className="chip">none yet</span>;
  if ((kind ?? g.kind) === 'evidence') return <span className="chip ok" title="a judgment question: the SQL returns the evidence, the answer is recorded beside it">evidence</span>;
  if (g.passed === true) return <span className="chip ok">passes</span>;
  if (g.passed === false) return <span className="chip warn">fails</span>;
  return <span className="chip warn">errored</span>;
}

const MATCH_LABEL: Record<GoldMatch, string> = {
  exact: 'recreates the gold exactly',
  exact_values: 'same rows as the gold; column names differ',
  reordered: 'same rows as the gold, other order',
  differs: 'differs from the gold',
};

function Match({ m }: { m: GoldMatch | '' | undefined }) {
  if (!m) return <span className="small muted">—</span>;
  return <span className={`chip ${m === 'exact' || m === 'exact_values' ? 'ok' : 'warn'}`}>{MATCH_LABEL[m]}</span>;
}

/** What the editor holds for a question: the SQL, where it started, and its kind. */
type Draft = { sql: string; source: string; kind: GoldenKind; expected: string };

/** A proposal's standing: written and checked outside the tab, waiting for you to confirm it. */
function Proposed({ p, golden }: { p: ProposalBrief | null; golden: { created_at: string } | null }) {
  if (!p) return <span className="small muted">—</span>;
  const confirmed = golden && golden.created_at >= p.created_at;
  const label = p.kind === 'evidence' ? 'evidence' : p.passed ? (p.gold_match === 'exact' || p.gold_match === 'exact_values' ? 'passes · exact' : 'passes') : p.passed === false ? 'fails' : 'errored';
  return (
    <span className={`chip ${confirmed ? '' : p.kind === 'evidence' || p.passed ? 'ok' : 'warn'}`} title={confirmed ? 'a golden was saved after this proposal' : 'waiting for you to review and save'}>
      {confirmed ? `reviewed · ${label}` : label}
    </span>
  );
}
const toReview = (q: { golden: { created_at: string } | null; proposal: ProposalBrief | null }) => !!q.proposal && !(q.golden && q.golden.created_at >= q.proposal.created_at);

/** Where a question stands, one bucket each, so the 54 add up. */
type GoldStatus = 'exact' | 'differs' | 'evidence' | 'fails' | 'waiting' | 'none';
/** Green / amber / red: the golden recreates the gold, covers it partly, or there is no working golden. */
type Tone = 'ok' | 'mid' | 'bad';
const STATUS: { key: GoldStatus; label: string; tone: Tone }[] = [
  { key: 'exact', label: 'recreates the gold exactly', tone: 'ok' },
  { key: 'differs', label: 'passes, differs from the gold', tone: 'mid' },
  { key: 'evidence', label: 'evidence (a judgment question)', tone: 'mid' },
  { key: 'fails', label: 'saved, fails its validator', tone: 'bad' },
  { key: 'waiting', label: 'no golden · a proposal waits', tone: 'bad' },
  { key: 'none', label: 'no golden, no proposal', tone: 'bad' },
];
const TONE: { key: Tone; label: string }[] = [
  { key: 'ok', label: 'exact: the golden recreates the gold answer' },
  { key: 'mid', label: 'partial: passes but differs, or evidence' },
  { key: 'bad', label: 'missing: no golden yet, or it fails' },
];
const toneOf = (q: Row): Tone => STATUS.find((s) => s.key === goldStatus(q))!.tone;
type Row = GoldenList['queries'][number];
function goldStatus(q: Row): GoldStatus {
  const g = q.golden;
  if (!g) return q.proposal ? 'waiting' : 'none';
  if (g.kind === 'evidence') return 'evidence';
  if (g.passed) return g.gold_match === 'exact' || g.gold_match === 'exact_values' ? 'exact' : 'differs';
  return 'fails';
}
/** How the golden's SQL began: a checked proposal, the SQL a run's agent wrote, or by hand. */
type GoldHow = 'proposal' | 'run' | 'hand';
const HOW: { key: GoldHow; label: string }[] = [
  { key: 'proposal', label: 'from a proposal' },
  { key: 'run', label: "from a run's SQL" },
  { key: 'hand', label: 'written by hand' },
];
const goldHow = (origin: string): GoldHow => (origin.startsWith('proposal') ? 'proposal' : origin ? 'run' : 'hand');

/** Golden coverage by dataset, like the Runs tab's pass rate by dataset: each bar split green / amber / red. A row filters the list. */
function CoverageChart({ queries, dataset, onDataset, compact }: { queries: Row[]; dataset: string; onDataset: (d: string) => void; compact: boolean }) {
  const groups = [
    { key: '', label: `all ${queries.length}`, qs: queries },
    ...(compact ? [] : [...new Set(queries.map((q) => q.dataset_key))].sort().map((d) => ({ key: d, label: d, qs: queries.filter((q) => q.dataset_key === d) }))),
  ];
  const W = 1000;
  const barH = 16;
  const rowH = 26;
  const top = 26;
  const H = top + groups.length * rowH + 6;
  const labelW = 180;
  const trackW = W - labelW - 160;
  return (
    <figure className="gcov">
      <p className="label">Fig · golden SQL coverage by dataset</p>
      <svg className="dia" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Golden SQL coverage by dataset: exact, partial and missing">
        <title>Golden SQL coverage by dataset</title>
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <g key={f}>
            <line className="ax" x1={labelW + f * trackW} x2={labelW + f * trackW} y1={top - 6} y2={H - 4} />
            <text className="tx k" x={labelW + f * trackW} y={top - 10} textAnchor="middle">
              {f * 100}%
            </text>
          </g>
        ))}
        {groups.map((g, i) => {
          const y = top + i * rowH + 4;
          const n = g.qs.length;
          const count = (t: Tone) => g.qs.filter((q) => toneOf(q) === t).length;
          let x = labelW;
          const pick = () => g.key && onDataset(g.key === dataset ? '' : g.key);
          return (
            <g
              key={g.key || 'all'}
              className={`cov ${g.key ? 'pick' : ''} ${g.key && g.key === dataset ? 'cur' : ''}`}
              onClick={pick}
              onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), pick())}
              tabIndex={g.key ? 0 : undefined}
              role={g.key ? 'button' : undefined}
              aria-pressed={g.key ? g.key === dataset : undefined}
            >
              <title>
                {g.label}: {TONE.map((t) => `${count(t.key)} ${t.label.split(':')[0]}`).join(' · ')} (of {n})
              </title>
              <text className={`tx ${g.key ? '' : 'all'}`} x={labelW - 10} y={y + 13} textAnchor="end">
                {g.label}
              </text>
              <rect className="bar" x={labelW} y={y} width={trackW} height={barH} opacity={0.3} />
              {TONE.map((t) => {
                const c = count(t.key);
                const w = (c / n) * trackW;
                const seg = (
                  <g key={t.key}>
                    {c > 0 && <rect className={`seg ${t.key}`} x={x} y={y} width={w} height={barH} />}
                    {c > 0 && w >= 22 && (
                      <text className="tx in" x={x + w / 2} y={y + 12.5} textAnchor="middle">
                        {c}
                      </text>
                    )}
                  </g>
                );
                x += w;
                return seg;
              })}
              <text className="tx k" x={labelW + trackW + 10} y={y + 13}>
                {count('ok') + count('mid')}/{n} · {count('ok')} exact
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption>
        {TONE.map((t) => (
          <span key={t.key} className="lg">
            <i className={`sw ${t.key}`} aria-hidden="true" /> {t.label}
          </span>
        ))}
        <span className="lg">At the right: covered (exact + partial) of the dataset's questions, then exact. Click a dataset to list only its questions.</span>
      </figcaption>
    </figure>
  );
}

/** The 54 split by golden status, and each status by how its SQL began. A row filters the list; with the editor open, only the bar. */
function GoldSummary({ queries, active, onPick, compact, dataset, onDataset }: { queries: Row[]; active: string; onPick: (s: GoldStatus) => void; compact: boolean; dataset: string; onDataset: (d: string) => void }) {
  const n = queries.length;
  const by = new Map(STATUS.map((s) => [s.key, queries.filter((q) => goldStatus(q) === s.key)]));
  const how = (rs: Row[], h: GoldHow) => rs.filter((q) => q.golden && goldHow(q.golden.origin) === h).length;
  return (
    <div className="gsum">
      <CoverageChart queries={queries} dataset={dataset} onDataset={onDataset} compact={compact} />
      {!compact && (
        <div className="tw">
          <table>
            <caption>
              {queries.filter((q) => q.golden).length} of {n} questions have golden SQL · a row shows only its questions
            </caption>
            <thead>
              <tr>
                <th>Status</th>
                <th className="num">Questions</th>
                {HOW.map((h) => (
                  <th key={h.key} className="num">
                    {h.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {STATUS.map((s) => {
                const rs = by.get(s.key)!;
                const saved = s.key !== 'waiting' && s.key !== 'none';
                return (
                  <tr key={s.key} className={`pickrow ${active === s.key ? 'cur' : ''}`} onClick={() => onPick(s.key)} aria-disabled={!rs.length}>
                    <td>
                      <i className={`sw ${s.tone}`} aria-hidden="true" />
                      <button type="button" className="linkish" aria-pressed={active === s.key} onClick={(e) => (e.stopPropagation(), onPick(s.key))}>
                        {s.label}
                      </button>
                    </td>
                    <td className="num">
                      {rs.length} of {n}
                    </td>
                    {HOW.map((h) => (
                      <td key={h.key} className="num muted">
                        {saved ? how(rs, h.key) || '·' : ''}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** The run picked on the list, with its trials by question. */
type PickedRun = { id: string; label: string; trials: Map<string, TrialRow[]> };

/** What the list page hands the editor it opens in place. */
type EditorCtx = {
  order: string[]; // question ids in the list's current order, for prev / next
  lens: string; // the list's `?…`, kept as the editor moves so the filter survives
  refresh: () => void; // re-read the coverage after a save
  drafts: Map<string, Draft>; // unsaved SQL per question, while this page is open
  run: PickedRun | null;
};

function runLabel(r: RunSummary): string {
  return `${r.agent}@${r.fingerprint.slice(0, 7)} · ${r.split} · ${ROLE_LABEL[r.role]}`;
}

/** A question's trials in the picked run: one verdict, or k of n passed. */
function RunVerdict({ rows }: { rows: TrialRow[] | undefined }) {
  if (!rows?.length) return <span className="small muted">not in this run</span>;
  const scored = rows.filter((r) => r.passed != null);
  const passed = scored.filter((r) => r.passed).length;
  if (!scored.length) return <span className="chip">not scored</span>;
  if (rows.length === 1) return <span className={`chip ${passed ? 'ok' : 'warn'}`}>{passed ? 'pass' : 'fail'}</span>;
  return <span className={`chip ${passed ? 'ok' : 'warn'}`}>{passed} of {scored.length} passed</span>;
}

const passedAny = (rows: TrialRow[] | undefined) => !!rows?.some((r) => r.passed);

/** The SQL the agent ran in a trial: every query_db call, in order. */
function sqlCalls(trace: Trace | null): (ToolCall & { k: number; sql: string })[] {
  return (trace?.tool_calls ?? [])
    .filter((c) => c.tool === 'query_db' && typeof c.input.sql === 'string')
    .map((c, i) => ({ ...c, k: i + 1, sql: String(c.input.sql).trim() }));
}

/** The SQL most likely behind the answer: the last error-free call whose output contains a piece of
 *  the agent's answer (`3.76` is in `3.7648…`), else the last error-free call. The last call is often a
 *  check the agent ran after it had the answer, so recency alone picks the wrong one. */
export function seedCall<T extends { error: boolean; output: string }>(calls: T[], answer: string): T | null {
  const bits = answer.split(/[^\p{L}\p{N}.]+/u).map((s) => s.replace(/\.+$/, '')).filter((s) => s.length >= 2);
  const ok = [...calls].reverse().filter((c) => !c.error);
  return ok.find((c) => bits.some((b) => c.output.includes(b))) ?? ok[0] ?? calls[calls.length - 1] ?? null;
}

/** The last value a fetch returned, kept while the next one loads, so a refresh never blanks the page. */
function useKept<T>(v: T | null): T | null {
  const [kept, setKept] = useState<T | null>(v);
  useEffect(() => {
    if (v) setKept(v);
  }, [v]);
  return v ?? kept;
}

/** Every question with its current golden SQL: the coverage you are curating. Picking a row opens the
 *  editor above the table, at `/golden/<ds>/<n>`, and the table stays (a nested route). */
export function Golden() {
  const { key, n } = useParams();
  const open = key && n ? `${key}/${n}` : null;
  const [sp, set] = useLens();
  const { search: lens } = useLocation();
  const nav = useNavigate();
  const [bump, setBump] = useState(0);
  const { data: fresh, error } = useGet<GoldenList>(`/api/golden${bump ? `?v=${bump}` : ''}`);
  const data = useKept(fresh);
  const drafts = useRef(new Map<string, Draft>());
  // the run whose verdicts and SQL seed the editor: `?run=<id>`, the champion by default, `?run=none` for none
  const { data: board } = useGet<Board>('/api/runs');
  const runs = (board?.runs ?? []).filter((r) => !r.dry_run && (r.scored ?? 0) > 0);
  const runParam = sp.get('run');
  const runId = runParam === 'none' ? null : runParam || board?.champion_run_id || runs[0]?.run_id || null;
  const { data: runDetail } = useGet<RunDetail>(runId ? `/api/runs/${runId}` : null);
  if (!data) return <Loading error={error} />;
  const only = sp.get('dataset') ?? '';
  const picked: PickedRun | null =
    runId && runDetail?.run_id === runId
      ? {
          id: runId,
          label: runLabel(runDetail),
          trials: runDetail.results.reduce((m, r) => m.set(r.query_id, [...(m.get(r.query_id) ?? []), r]), new Map<string, TrialRow[]>()),
        }
      : null;
  const verdict = picked ? sp.get('verdict') ?? '' : '';
  const show = sp.get('show') ?? '';
  const status = sp.get('status') ?? '';
  const rows = data.queries
    .filter((q) => !status || goldStatus(q) === status)
    .filter((q) => !only || q.dataset_key === only)
    .filter((q) => show !== 'review' || toReview(q))
    .filter((q) => !verdict || (verdict === 'pass' ? passedAny(picked?.trials.get(q.id)) : picked?.trials.has(q.id) && !passedAny(picked.trials.get(q.id))));
  const inRun = picked ? data.queries.filter((q) => picked.trials.has(q.id)) : [];
  const datasets = [...new Set(data.queries.map((q) => q.dataset_key))].sort();
  const order = (open && !rows.some((q) => q.id === open) ? data.queries : rows).map((q) => q.id);
  const ctx: EditorCtx = { order, lens, refresh: () => setBump((b) => b + 1), drafts: drafts.current, run: picked };
  return (
    <>
      <p className="label">Golden SQL</p>
      <h1>
        Golden SQL is the key step an LLM needs to reach each answer, and this process has <em>found</em> it for{' '}
        {data.queries.filter((q) => toneOf(q) !== 'bad').length} of {data.n} questions
      </h1>
      <GoldSummary
        queries={data.queries}
        active={status}
        onPick={(k) => set({ status: k === status ? null : k })}
        compact={!!open}
        dataset={only}
        onDataset={(d) => set({ dataset: d || null })}
      />
      <Outlet context={ctx} />
      <div className="filters">
        <label className="pick">
          <span className="label">dataset</span>
          <select value={only} onChange={(e) => set({ dataset: e.target.value || null })} aria-label="dataset">
            <option value="">all {data.n}</option>
            {datasets.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        <label className="pick">
          <span className="label">run · seeds the editor</span>
          <select value={runId ?? 'none'} onChange={(e) => set({ run: e.target.value, verdict: null })} aria-label="run">
            <option value="none">— none, start from scratch —</option>
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.run_id === board?.champion_run_id ? '★ ' : ''}
                {runLabel(r)} · {r.passed ?? 0}/{r.scored ?? 0} · {r.run_id.slice(0, 16)}
              </option>
            ))}
          </select>
        </label>
        <label className="pick">
          <span className="label">show</span>
          <select value={show} onChange={(e) => set({ show: e.target.value || null })} aria-label="show">
            <option value="">every question</option>
            <option value="review">proposals to review ({data.queries.filter(toReview).length})</option>
          </select>
        </label>
        {picked && (
          <label className="pick">
            <span className="label">in that run</span>
            <select value={verdict} onChange={(e) => set({ verdict: e.target.value || null })} aria-label="verdict in the run">
              <option value="">any verdict</option>
              <option value="pass">passed</option>
              <option value="fail">failed</option>
            </select>
          </label>
        )}
        <span className="count">
          {rows.length} of {data.n} shown
          {picked && ` · the run answered ${inRun.length} of ${data.n}, ${inRun.filter((q) => passedAny(picked.trials.get(q.id))).length} passed`}
        </span>
      </div>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>Query</th>
              <th>Question</th>
              <th>Style</th>
              <th>In the run</th>
              <th>Proposed</th>
              <th>Golden</th>
              <th>Against the gold</th>
              <th className="num">Saves</th>
              <th>Last saved</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((q) => (
              <tr key={q.id} className={`pickrow ${q.id === open ? 'cur' : ''}`} onClick={() => nav(`${goldenPath(q.id)}${lens}`)}>
                <td className="sub">
                  <Link to={`${goldenPath(q.id)}${lens}`} aria-current={q.id === open ? 'true' : undefined} onClick={(e) => e.stopPropagation()}>
                    {q.id}
                  </Link>
                </td>
                <td>
                  <Clip text={q.question} at={110} />
                </td>
                <td className="small">{STYLE_LABEL[q.validator_style] ?? q.validator_style}</td>
                <td>{picked ? <RunVerdict rows={picked.trials.get(q.id)} /> : <span className="small muted">—</span>}</td>
                <td>
                  <Proposed p={q.proposal} golden={q.golden} />
                </td>
                <td>
                  <Status g={q.golden} />
                </td>
                <td>
                  <Match m={q.golden?.gold_match} />
                </td>
                <td className="num">{q.golden ? q.golden.versions : '—'}</td>
                <td className="small mono">{q.golden ? q.golden.created_at.slice(0, 16).replace('T', ' ') : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/** One question, opened in place above the list: write the SQL, run it as dab_agent, see what the
 *  validator and the gold itself say, save it. */
export function GoldenEditor() {
  const { key = '', n = '' } = useParams();
  const id = `${key}/${n}`;
  const { order, lens, refresh, drafts, run } = useOutletContext<EditorCtx>();
  const [bump, setBump] = useState(0);
  const { data: fresh, error } = useGet<GoldenOne>(`/api/golden/${key}/${n}${bump ? `?v=${bump}` : ''}`);
  const kept = useKept(fresh);
  const data = fresh ?? (kept?.query.id === id ? kept : null);
  const [sql, setSql] = useState('');
  const [source, setSource] = useState(''); // where the SQL in the editor started
  // the picked run's trial of this question: the first that passed, else the first; a select picks another
  const trials = run?.trials.get(id) ?? [];
  const [pick, setPick] = useState<number | null>(null);
  useEffect(() => setPick(null), [id, run?.id]);
  const trial = trials.find((r) => r.trial === pick) ?? trials.find((r) => r.passed) ?? trials[0] ?? null;
  const { data: rawTrace } = useGet<Trace>(run && trial?.trace_file ? apiTrialPath(run.id, trialId(trial)) : null);
  const trace = rawTrace && trial && rawTrace.query_id === id && rawTrace.trial === trial.trial ? rawTrace : null;
  const calls = sqlCalls(trace);
  // a version that answers with SQL submitted one statement: that is the seed; else guess from its query_db calls
  const submitted = trace?.submission?.sql ? { sql: trace.submission.sql, k: 0 } : null;
  const seed = submitted ?? seedCall(calls, trial?.answer ?? '');
  const from = (c: { k: number }) => (run && trial ? `run ${run.id} · ${trialId(trial)} · ${c.k === 0 ? 'submitted SQL' : `query_db #${c.k}`}` : '');
  const [note, setNote] = useState('');
  const [res, setRes] = useState<GoldenAttempt | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<'run' | 'save' | null>(null);
  const [kind, setKind] = useState<GoldenKind>('answer');
  const [expected, setExpected] = useState(''); // evidence only: the answer a reader reaches
  const panel = useRef<HTMLElement>(null);
  const loaded = data?.query.id;
  useEffect(() => {
    if (!loaded) return;
    setNote('');
    setRes(null);
    setErr(null);
    // the row picked may be far down the list; bring the editor, which sits above it, into view
    panel.current?.scrollIntoView({ block: 'start' });
  }, [loaded]);
  const seedKey = seed ? from(seed) : '';
  const prop = data?.proposal ?? null;
  const propKey = prop ? `proposal #${prop.id}` : '';
  useEffect(() => {
    // what the editor starts from: your unsaved draft, else the current golden, else the proposal,
    // else the run's SQL, else nothing
    if (!loaded) return;
    const cur = data?.current;
    const d: Draft = drafts.get(loaded) ??
      (cur ? { sql: cur.sql, source: `golden #${cur.id}`, kind: cur.kind, expected: cur.expected_answer }
      : prop ? { sql: prop.sql, source: propKey, kind: prop.kind, expected: prop.expected_answer }
      : seed ? { sql: seed.sql, source: seedKey, kind: 'answer', expected: '' }
      : { sql: '', source: '', kind: 'answer', expected: '' });
    setSql(d.sql);
    setSource(d.source);
    setKind(d.kind);
    setExpected(d.expected);
  }, [loaded, seedKey, propKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const at = order.indexOf(id);
  const prev = at > 0 ? order[at - 1] : null;
  const next = at >= 0 && at < order.length - 1 ? order[at + 1] : null;
  const nav = (
    <p className="small editor-nav">
      {prev ? <Link to={`${goldenPath(prev)}${lens}`}>← {prev}</Link> : <span className="muted">first</span>}
      {' · '}
      {next ? <Link to={`${goldenPath(next)}${lens}`}>{next} →</Link> : <span className="muted">last</span>}
      {' · '}
      <Link to={`${goldenPath()}${lens}`}>close</Link>
    </p>
  );
  if (!data)
    return (
      <section className="card golden-editor" ref={panel} aria-label={`golden SQL for ${id}`}>
        {nav}
        <Loading error={error} />
      </section>
    );
  const q = data.query;
  const edit = (patch: Partial<Draft>) => {
    const d: Draft = { sql, source, kind, expected, ...patch };
    setSql(d.sql);
    setSource(d.source);
    setKind(d.kind);
    setExpected(d.expected);
    drafts.set(q.id, d);
  };
  async function go(action: 'run' | 'save') {
    setBusy(action);
    setErr(null);
    try {
      const r = await post<GoldenAttempt>(`/api/golden/${key}/${n}${action === 'run' ? '/run' : ''}`, { sql, note, source, kind, expected_answer: kind === 'evidence' ? expected : '' });
      setRes(r);
      if (action === 'save') {
        setNote('');
        setBump((b) => b + 1);
        refresh();
      }
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  const cur = data.current;
  return (
    <section className="card golden-editor" ref={panel} aria-label={`golden SQL for ${q.id}`}>
      <div className="editor-head">
        <p className="label">
          editing {q.id} · {STYLE_LABEL[q.validator_style] ?? q.validator_style} validator · <Link to={questionPath(q.id)}>the question page</Link> ·{' '}
          <Link to={datasetPath(q.dataset_key)}>its tables</Link>
        </p>
        {nav}
      </div>
      {run &&
        (trial ? (
          <div className={`answer ${trial.passed == null ? '' : trial.passed ? 'ok' : 'no'}`}>
            <p className="label">
              {run.label} · trial {trial.trial} · {trial.passed == null ? 'not scored' : trial.passed ? 'pass' : 'fail'}
              {trials.length > 1 && (
                <>
                  {' · '}
                  <select value={trial.trial} onChange={(e) => setPick(Number(e.target.value))} aria-label="trial">
                    {trials.map((r) => (
                      <option key={r.trial} value={r.trial}>
                        t{r.trial} · {r.passed == null ? 'not scored' : r.passed ? 'pass' : 'fail'}
                      </option>
                    ))}
                  </select>
                </>
              )}
            </p>
            <pre className="wrap-any">{trial.answer || '(no answer)'}</pre>
            {!trial.passed && trial.reason && <p className="reason">{trial.reason}</p>}
            {trace?.score && trace.score.golden_id != null && <SqlVersus score={trace.score} agentSql={trace.submission?.sql} golden={trace.golden} mode={trace.submission?.mode} step={trace.submission?.step} reason={trial.reason} plan={trace.submission?.plan} />}
            <p className="small">
              {trace ? `${calls.length} query_db call${calls.length === 1 ? '' : 's'}` : 'loading its SQL…'}
              {submitted && ', then one submitted statement (the editor starts from it)'}
              {trace && trace.tool_calls.some((c) => c.tool === 'execute_python') && ' and some execute_python: the answer may have been finished in Python, so the SQL alone may not reproduce it'}
              {' · '}
              <Link to={trialPath(run.id, trialId(trial))}>the full trace</Link>
            </p>
          </div>
        ) : (
          <p className="small muted">{run.label} did not run {id}; the editor starts empty.</p>
        ))}
      {prop && (
        <div className={`answer ${prop.kind === 'evidence' || prop.passed ? 'ok' : 'no'}`}>
          <p className="label">
            proposed #{prop.id} · {prop.kind} · {prop.kind === 'evidence' ? 'not judged' : prop.passed ? 'passes' : prop.passed === false ? 'fails' : 'errored'}
            {prop.gold_match && ` · ${MATCH_LABEL[prop.gold_match]}`} · {prop.duration_ms ?? '—'} ms · by {prop.author}, {prop.created_at.slice(0, 10)}
          </p>
          {prop.replaces && <p className="small">Replaces: {prop.replaces}</p>}
          {prop.note && <p className="small">{prop.note}</p>}
          {prop.kind === 'evidence' && <p className="small">Expected answer: <b>{prop.expected_answer}</b></p>}
          <p className="small">
            {source === propKey ? (
              sql.trim() === prop.sql.trim() ? (
                <>In the editor, unchanged. Run and check, then confirm it.</>
              ) : (
                <>In the editor, edited.</>
              )
            ) : (
              <button type="button" className="more" onClick={() => edit({ sql: prop.sql, source: propKey, kind: prop.kind, expected: prop.expected_answer })}>
                load the proposal into the editor
              </button>
            )}
          </p>
        </div>
      )}
      <h2>
        {q.id}{' '}
        {cur
          ? cur.gold_match === 'exact' || cur.gold_match === 'exact_values'
            ? 'has golden SQL that recreates the gold answer'
            : cur.passed
              ? "has golden SQL that passes its validator but doesn't match the gold exactly"
              : 'has golden SQL that does not pass yet'
          : 'has no golden SQL yet'}
      </h2>
      <p className="lead">{q.question}</p>
      <div className="tw">
        <table>
          <tbody>
            <tr>
              <td className="sub">Gold answer</td>
              <td className="gold-cell">
                <Gold preview={q.gold_preview} lines={q.gold_lines} full={q.gold_text} />
              </td>
            </tr>
            {data.hints && (
              <tr>
                <td className="sub">Hints</td>
                <td>
                  <Clip text={data.hints} at={220} />
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <form
        className="toolform"
        onSubmit={(e) => {
          e.preventDefault();
          if (!busy && sql.trim()) void go('run');
        }}
      >
        <label className="field">
          <span className="label">
            SQL · runs as dab_agent · read-only · 60 s · search_path dataagentbench (tables are {q.dataset_key}_*) · {source ? `started from ${source.replace(/^run \S+ · /, '')}` : 'by hand'}
          </span>
          <SqlEditor value={sql} onChange={(v) => edit({ sql: v })} rows={14} placeholder={`select … from ${q.dataset_key}_…`} ariaLabel={`golden SQL for ${q.id}`} />
        </label>
        <div className="filters" role="radiogroup" aria-label="kind">
          <label className="pick">
            <input type="radio" name="kind" checked={kind === 'answer'} onChange={() => edit({ kind: 'answer' })} /> answer · the result is judged by the validator
          </label>
          <label className="pick">
            <input type="radio" name="kind" checked={kind === 'evidence'} onChange={() => edit({ kind: 'evidence' })} /> evidence · a judgment question: the rows are what a reader needs
          </label>
        </div>
        {kind === 'evidence' && (
          <label className="field">
            <span className="label">expected answer · what a reader concludes from the rows (the gold: {q.gold_preview})</span>
            <input type="text" value={expected} onChange={(e) => edit({ expected: e.target.value })} />
          </label>
        )}
        <label className="field">
          <span className="label">note · optional, saved with it</span>
          <input type="text" value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        <div className="filters">
          <button type="submit" className="btn" disabled={!!busy || !sql.trim()}>
            {busy === 'run' ? 'Running…' : 'Run and check'}
          </button>
          <button type="button" className="btn" disabled={!!busy || !sql.trim()} onClick={() => void go('save')}>
            {busy === 'save' ? 'Saving…' : prop && source === propKey && sql.trim() === prop.sql.trim() ? 'Confirm the proposal as golden' : 'Save as golden'}
          </button>
          <span className="count">a save runs and judges it again; a failing golden is saved too and says so</span>
        </div>
        {err && <div className="code err">{err}</div>}
      </form>

      {res && (
        <>
          <div className="chips" style={{ marginTop: 'var(--s4)' }}>
            <Status g={res.verdict} kind={res.kind} />
            <Match m={res.gold_match.match} />
            <span className="chip">
              {fmtInt(res.execution.row_count)}
              {res.execution.truncated ? '+' : ''} rows · {res.execution.duration_ms} ms
            </span>
            {res.saved && <span className="chip ok">saved #{res.saved.id}</span>}
          </div>
          <div className={`code ${res.verdict.passed ? '' : 'err'}`}>
            <p className="label">validator</p>
            <pre>{res.verdict.reason || '—'}</pre>
          </div>
          <div className={`code ${res.gold_match.match === 'exact' || res.gold_match.match === 'exact_values' ? '' : 'err'}`}>
            <p className="label">against the gold answer itself</p>
            <pre>{res.gold_match.detail}</pre>
          </div>
          {res.gold_diff?.length > 0 && <GoldDiff key={res.answer_text} lines={res.gold_diff} />}
          {res.answer_text && (
            <div className="code">
              <p className="label">what the validator read (the result rendered like the gold)</p>
              <pre>{res.answer_text.length > 4000 ? `${res.answer_text.slice(0, 4000)}\n…` : res.answer_text}</pre>
            </div>
          )}
          {res.execution.columns.length > 0 && res.execution.rows.length > 1 && (
            <div className="tw result-scroll">
              <table>
                <thead>
                  <tr>
                    {res.execution.columns.map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {res.execution.rows.slice(0, 50).map((r, i) => (
                    <tr key={i}>
                      {r.map((v, j) => (
                        <td key={j} className="small mono">
                          {v == null ? 'NULL' : String(v)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {run && trial && calls.length > 0 && (
        <>
          <h3>
            The agent's SQL in {trialId(trial)}: {calls.length} call{calls.length === 1 ? '' : 's'}, {calls.filter((c) => c.error).length} errored
          </h3>
          <ol className="sqlcalls">
            {calls.map((c) => (
              <li key={c.k} className={c.error ? 'err' : ''}>
                <div className="sqlcall-head">
                  <span className="label">
                    query_db #{c.k} · {c.error ? 'error' : `${c.output.split('\n').length - 1} lines out`} · {c.elapsed_s.toFixed(1)} s
                  </span>
                  {source === from(c) ? (
                    <span className="chip ok">in the editor</span>
                  ) : (
                    <button type="button" className="more" onClick={() => edit({ sql: c.sql, source: from(c), kind: 'answer', expected: '' })}>
                      load into the editor
                    </button>
                  )}
                </div>
                <SqlBlock sql={c.sql} maxHeight={360} />
                <details>
                  <summary>what it returned</summary>
                  <pre>{c.output.length > 2000 ? `${c.output.slice(0, 2000)}\n…` : c.output}</pre>
                </details>
              </li>
            ))}
          </ol>
        </>
      )}

      {data.ledger && cur && (
        <details className="golden-steps">
          <summary>The current golden (#{cur.id}), step by step, as the reader wrote it</summary>
          <StepsTable golden={data.ledger} />
        </details>
      )}
      <h3>{data.history.length === 0 ? 'No saves yet' : `${data.history.length} save${data.history.length === 1 ? '' : 's'}, newest first; the top one is current`}</h3>
      {data.history.length > 0 && (
        <div className="tw">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Saved</th>
                <th>Verdict</th>
                <th>Against the gold</th>
                <th className="num">Rows</th>
                <th>Note</th>
                <th>Started from</th>
                <th>SQL</th>
              </tr>
            </thead>
            <tbody>
              {data.history.map((h) => (
                <tr key={h.id}>
                  <td className="mono small">{h.id}</td>
                  <td className="mono small">
                    {h.created_at.slice(0, 16).replace('T', ' ')} · {h.author}
                  </td>
                  <td>
                    <Status g={h} />
                  </td>
                  <td>
                    <Match m={h.gold_match} />
                  </td>
                  <td className="num">{h.row_count ?? '—'}</td>
                  <td className="small">{h.note || '—'}</td>
                  <td className="small mono">{h.source ? h.source.replace(/^run (\S{16})\S* · /, 'run $1… · ') : 'by hand'}</td>
                  <td>
                    <button type="button" className="more" onClick={() => edit({ sql: h.sql, source: `golden #${h.id}`, kind: h.kind, expected: h.expected_answer })}>
                      load into the editor
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
