import { useEffect, useRef, useState } from 'react';
import { Link, Outlet, useLocation, useNavigate, useOutletContext, useParams } from 'react-router-dom';
import { type GoldMatch, type GoldenAttempt, type GoldenBrief, type GoldenList, type GoldenOne, STYLE_LABEL, fmtInt, post, useGet } from '../lib/api';
import { Clip, Gold, Loading } from '../lib/ui';
import { datasetPath, goldenPath, questionPath, useLens } from '../lib/url';

function Status({ g }: { g: GoldenBrief | { passed: boolean | null } | null }) {
  if (!g) return <span className="chip">none yet</span>;
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

/** What the list page hands the editor it opens in place. */
type EditorCtx = {
  order: string[]; // question ids in the list's current order, for prev / next
  lens: string; // the list's `?…`, kept as the editor moves so the filter survives
  refresh: () => void; // re-read the coverage after a save
  drafts: Map<string, string>; // unsaved SQL per question, while this page is open
};

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
  const drafts = useRef(new Map<string, string>());
  if (!data) return <Loading error={error} />;
  const only = sp.get('dataset') ?? '';
  const rows = data.queries.filter((q) => !only || q.dataset_key === only);
  const datasets = [...new Set(data.queries.map((q) => q.dataset_key))].sort();
  const order = (open && !rows.some((q) => q.id === open) ? data.queries : rows).map((q) => q.id);
  const ctx: EditorCtx = { order, lens, refresh: () => setBump((b) => b + 1), drafts: drafts.current };
  return (
    <>
      <p className="label">golden · SQL by hand, run as the agent's role, judged by the question's validator</p>
      <h1>
        {data.written} of {data.n} questions have golden SQL; {data.exact} of {data.n} <em>recreate</em> the gold answer and {data.passing} of {data.n} pass their validator
      </h1>
      <p className="lead">
        A golden is one Postgres query that reproduces a question's gold answer. It runs as <code>dab_agent</code>, read-only, over exactly the tables the agent sees, so a
        passing golden proves the question is answerable in SQL. Every save is kept; the newest is current. Goldens live in <code>dataagentbench_meta</code>, which the agent's role
        cannot read, and never reach a prompt. Pick a question below; its editor opens here and the list stays.
      </p>
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
        <span className="count">
          {rows.length} of {data.n} shown
        </span>
      </div>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>Query</th>
              <th>Question</th>
              <th>Style</th>
              <th>Validator</th>
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
  const { order, lens, refresh, drafts } = useOutletContext<EditorCtx>();
  const [bump, setBump] = useState(0);
  const { data: fresh, error } = useGet<GoldenOne>(`/api/golden/${key}/${n}${bump ? `?v=${bump}` : ''}`);
  const kept = useKept(fresh);
  const data = fresh ?? (kept?.query.id === id ? kept : null);
  const [sql, setSql] = useState('');
  const [note, setNote] = useState('');
  const [res, setRes] = useState<GoldenAttempt | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<'run' | 'save' | null>(null);
  const panel = useRef<HTMLElement>(null);
  const loaded = data?.query.id;
  useEffect(() => {
    // a new question: start from its unsaved draft, else its current golden, else empty
    if (!loaded) return;
    setSql(drafts.get(loaded) ?? data?.current?.sql ?? '');
    setNote('');
    setRes(null);
    setErr(null);
    // the row picked may be far down the list; bring the editor, which sits above it, into view
    panel.current?.scrollIntoView({ block: 'start' });
  }, [loaded]); // eslint-disable-line react-hooks/exhaustive-deps

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
  const edit = (v: string) => {
    setSql(v);
    drafts.set(q.id, v);
  };
  async function go(kind: 'run' | 'save') {
    setBusy(kind);
    setErr(null);
    try {
      const r = await post<GoldenAttempt>(`/api/golden/${key}/${n}${kind === 'run' ? '/run' : ''}`, { sql, note });
      setRes(r);
      if (kind === 'save') {
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
          <span className="label">SQL · runs as dab_agent · read-only · 60 s · search_path dataagentbench (tables are {q.dataset_key}_*)</span>
          <textarea value={sql} onChange={(e) => edit(e.target.value)} rows={12} spellCheck={false} placeholder={`select … from ${q.dataset_key}_…`} />
        </label>
        <label className="field">
          <span className="label">note · optional, saved with it</span>
          <input type="text" value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        <div className="filters">
          <button type="submit" className="btn" disabled={!!busy || !sql.trim()}>
            {busy === 'run' ? 'Running…' : 'Run and check'}
          </button>
          <button type="button" className="btn" disabled={!!busy || !sql.trim()} onClick={() => void go('save')}>
            {busy === 'save' ? 'Saving…' : 'Save as golden'}
          </button>
          <span className="count">a save runs and judges it again; a failing golden is saved too and says so</span>
        </div>
        {err && <div className="code err">{err}</div>}
      </form>

      {res && (
        <>
          <div className="chips" style={{ marginTop: 'var(--s4)' }}>
            <Status g={res.verdict} />
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
                  <td>
                    <button type="button" className="more" onClick={() => edit(h.sql)}>
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
