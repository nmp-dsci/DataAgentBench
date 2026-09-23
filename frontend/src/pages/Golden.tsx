import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { type GoldenAttempt, type GoldenBrief, type GoldenList, type GoldenOne, STYLE_LABEL, fmtInt, post, queryPath, useGet } from '../lib/api';
import { Clip, Gold, Loading } from '../lib/ui';

function Status({ g }: { g: GoldenBrief | { passed: boolean | null } | null }) {
  if (!g) return <span className="chip">none yet</span>;
  if (g.passed === true) return <span className="chip ok">passes</span>;
  if (g.passed === false) return <span className="chip warn">fails</span>;
  return <span className="chip warn">errored</span>;
}

/** Every question with its current golden SQL: the coverage you are curating. */
export function Golden() {
  const { data, error } = useGet<GoldenList>('/api/golden');
  const [only, setOnly] = useState<string>('');
  if (!data) return <Loading error={error} />;
  const rows = data.queries.filter((q) => !only || q.dataset_key === only);
  const datasets = [...new Set(data.queries.map((q) => q.dataset_key))].sort();
  return (
    <>
      <p className="label">golden · SQL by hand, run as the agent's role, judged by the question's validator</p>
      <h1>
        {data.written} of {data.n} questions have golden SQL, and {data.passing} of {data.n} <em>pass</em> their validator
      </h1>
      <p className="lead">
        A golden is one Postgres query that reproduces a question's gold answer. It runs as <code>dab_agent</code>, read-only, over exactly the tables the agent sees, so a
        passing golden proves the question is answerable in SQL. Every save is kept; the newest is current. Goldens live in <code>dataagentbench_meta</code>, which the agent's role
        cannot read, and never reach a prompt.
      </p>
      <div className="filters">
        <label className="pick">
          <span className="label">dataset</span>
          <select value={only} onChange={(e) => setOnly(e.target.value)} aria-label="dataset">
            <option value="">all {data.n}</option>
            {datasets.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>Query</th>
              <th>Question</th>
              <th>Validator</th>
              <th>Golden</th>
              <th className="num">Saves</th>
              <th>Last saved</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((q) => (
              <tr key={q.id}>
                <td className="sub">
                  <Link to={`/golden/${q.id}`}>{q.id}</Link>
                </td>
                <td>
                  <Clip text={q.question} at={110} />
                </td>
                <td className="small">{STYLE_LABEL[q.validator_style] ?? q.validator_style}</td>
                <td>
                  <Status g={q.golden} />
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

/** One question: write the SQL, run it as dab_agent, see what the validator says, save it. */
export function GoldenQuery() {
  const { key = '', n = '' } = useParams();
  const [bump, setBump] = useState(0);
  const { data, error } = useGet<GoldenOne>(`/api/golden/${key}/${n}?v=${bump}`);
  const [sql, setSql] = useState('');
  const [note, setNote] = useState('');
  const [res, setRes] = useState<GoldenAttempt | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<'run' | 'save' | null>(null);
  const loaded = data?.query.id;
  useEffect(() => {
    // a new question (or first load): start from its current golden, else empty
    setSql(data?.current?.sql ?? '');
    setRes(null);
    setErr(null);
  }, [loaded]);
  if (!data) return <Loading error={error} />;
  const q = data.query;
  async function go(kind: 'run' | 'save') {
    setBusy(kind);
    setErr(null);
    try {
      const r = await post<GoldenAttempt>(`/api/golden/${key}/${n}${kind === 'run' ? '/run' : ''}`, { sql, note });
      setRes(r);
      if (kind === 'save') {
        setNote('');
        setBump((b) => b + 1);
      }
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  const cur = data.current;
  return (
    <>
      <p className="label">
        <Link to="/golden">golden</Link> · {q.id} · {STYLE_LABEL[q.validator_style] ?? q.validator_style} validator ·{' '}
        <Link to={queryPath(q.id)}>the question page</Link> · <Link to={`/datasets/${q.dataset_key}`}>its tables</Link>
      </p>
      <h1>
        {q.id}{' '}
        {cur ? (
          cur.passed ? (
            <>
              has golden SQL that <em>passes</em> its validator
            </>
          ) : (
            <>
              has golden SQL that does <em>not</em> pass yet
            </>
          )
        ) : (
          <>
            has <em>no</em> golden SQL yet
          </>
        )}
      </h1>
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
          <textarea value={sql} onChange={(e) => setSql(e.target.value)} rows={12} spellCheck={false} placeholder={`select … from ${q.dataset_key}_…`} />
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
          {res.answer_text && (
            <div className="code">
              <p className="label">what the validator read (the result rendered like the gold)</p>
              <pre>{res.answer_text.length > 4000 ? `${res.answer_text.slice(0, 4000)}\n…` : res.answer_text}</pre>
            </div>
          )}
          {res.execution.columns.length > 0 && res.execution.rows.length > 1 && (
            <div className="tw">
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

      <h2>
        {data.history.length === 0 ? 'No saves yet' : `${data.history.length} save${data.history.length === 1 ? '' : 's'}, newest first; the top one is current`}
      </h2>
      {data.history.length > 0 && (
        <div className="tw">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Saved</th>
                <th>Verdict</th>
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
                  <td className="num">{h.row_count ?? '—'}</td>
                  <td className="small">{h.note || '—'}</td>
                  <td>
                    <button type="button" className="more" onClick={() => setSql(h.sql)}>
                      load into the editor
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
