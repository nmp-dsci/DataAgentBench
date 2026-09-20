import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { type QueryDetail, type QuerySummary, type TrialFile, STYLE_LABEL, fmtBytes, fmtPct, queryPath, useGet } from '../lib/api';
import { Loading, Rate } from '../lib/ui';

export function Query() {
  const { key, n } = useParams();
  const { data: q, error } = useGet<QueryDetail>(key && n ? `/api/queries/${key}/${n}` : null);
  const { data: all } = useGet<QuerySummary[]>('/api/queries');
  const [showHints, setShowHints] = useState(false);
  if (!q) return <Loading error={error} />;

  const siblings = (all ?? []).filter((x) => x.dataset_key === q.dataset_key);
  const idx = siblings.findIndex((x) => x.id === q.id);
  const prev = idx > 0 ? siblings[idx - 1] : null;
  const next = idx >= 0 && idx < siblings.length - 1 ? siblings[idx + 1] : null;
  const t = q.trials;
  const rate = t?.rescored && t.passed != null ? t.passed / t.n : null;
  const files = (t?.files ?? []).slice().sort((a, b) => (b.passed ?? 0) / b.n - (a.passed ?? 0) / a.n || b.n - a.n);
  const verdict = rate == null ? 'not scored' : rate === 0 ? 'never passed' : rate < 0.1 ? 'rarely passed' : rate >= 0.95 ? 'almost always passed' : 'passed';

  return (
    <>
      <p className="crumbs">
        <Link to="/queries">Queries</Link> › <Link to={`/datasets/${q.dataset_key}`}>{q.dataset_key}</Link> › {q.query_id}
      </p>
      <p className="label">
        {q.id} · {STYLE_LABEL[q.validator.style] ?? q.validator.style} validator · gold {q.gold_lines} {q.gold_lines === 1 ? 'line' : 'lines'}
      </p>
      <h1>
        {q.id} — {verdict}
        {rate != null ? ` in ${fmtPct(rate)} of ${t?.n} published trials` : ''}
        {q.footnote ? '; gold revised upstream' : ''}
      </h1>
      <p className="lead">
        Over {q.dataset.n_dbs} databases ({q.dataset.engines.join(', ')}, {fmtBytes(q.dataset.bytes_total)}). The question is shown verbatim from <code>query.json</code>; the gold from{' '}
        <code>ground_truth.csv</code>; the validator is the file that decides.
      </p>

      <div className="grid2">
        <div>
          <h3>Question</h3>
          <div className="question">{q.question}</div>
          {q.site_text_matches === false && (
            <p className="small muted">
              <span className="tag">wording differs from the site's queries.json</span> — the repo's text is shown; the public site still carries an older wording.
            </p>
          )}
          <h3>Gold</h3>
          <div className="gold">{q.gold_text}</div>
          {q.footnote && (
            <p className="small">
              <span className="tag warn">revised</span> {q.footnote}
            </p>
          )}
          <dl className="kv">
            <dt>dataset</dt>
            <dd>
              <Link to={`/datasets/${q.dataset_key}`}>{q.dataset_key}</Link> · {q.dataset.n_queries} queries
            </dd>
            <dt>engines</dt>
            <dd>{q.dataset.engines.join(', ')}</dd>
            <dt>leaderboard</dt>
            <dd>{q.on_site ? 'on the site · ' : ''}{t ? `${t.n} published trials in ${t.files.length} answer files` : 'no published trials'}</dd>
            <dt>hints</dt>
            <dd>
              {q.hints ? (
                <>
                  {fmtBytes(q.hints.length)} ·{' '}
                  <button type="button" className="linkbtn" onClick={() => setShowHints((v) => !v)}>
                    {showHints ? 'hide' : 'show'}
                  </button>
                </>
              ) : (
                'none'
              )}
            </dd>
          </dl>
          {showHints && (
            <div className="code band">
              <p className="label">db_description_withhint.txt</p>
              <pre>{q.hints}</pre>
            </div>
          )}
        </div>
        <div>
          <h3>
            validate.py · {STYLE_LABEL[q.validator.style] ?? q.validator.style} · {q.validator.lines} lines
          </h3>
          <div className="code">
            <pre>{q.validator.source}</pre>
          </div>
        </div>
      </div>

      <h2>
        {t?.rescored ? `Published trials, per answer file — ${t.passed} of ${t.n} passed` : t ? `${t.n} published answers in ${t.files.length} files, not yet judged` : 'No published trials'}
      </h2>
      {t?.rescored && (
        <p>
          Each file's rows judged by the validator above, with up to three passing and three failing answers shown verbatim and the validator's own reason string on each failure.
          {t.timed_out ? ` ${t.timed_out} calls hit the timeout and count as fails.` : ''}
        </p>
      )}
      {t && (
        <div className="tw">
          <table>
            <thead>
              <tr>
                <th>Answer file</th>
                <th className="num">Rank</th>
                <th className="num">Trials</th>
                <th>Passed</th>
              </tr>
            </thead>
            <tbody>
              {files.map((f) => (
                <tr key={f.name}>
                  <td className="sub">
                    {f.label}
                    <span className="path">{f.name}</span>
                  </td>
                  <td className="num">{f.rank ?? '—'}</td>
                  <td className="num">{f.n}</td>
                  <td>
                    <Rate passed={f.passed} n={f.n} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {t?.rescored && files.map((f) => <Examples key={f.name} f={f} />)}

      <p className="small" style={{ marginTop: 'var(--s7)' }}>
        {prev && (
          <>
            <Link to={queryPath(prev.id)}>← {prev.id}</Link>
            {' · '}
          </>
        )}
        <Link to={`/datasets/${q.dataset_key}`}>all {q.dataset_key} queries</Link>
        {next && (
          <>
            {' · '}
            <Link to={queryPath(next.id)}>{next.id} →</Link>
          </>
        )}
      </p>
    </>
  );
}

function Examples({ f }: { f: TrialFile }) {
  const passes = f.passes ?? [];
  const fails = f.fails ?? [];
  if (!passes.length && !fails.length) return null;
  return (
    <details>
      <summary>
        {f.label}: {passes.length ? `${passes.length} passing` : 'no passing'} and {fails.length ? `${fails.length} failing` : 'no failing'} example
        {passes.length + fails.length === 1 ? '' : 's'} of {f.passed}/{f.n}
      </summary>
      {passes.map((p) => (
        <div key={`p${p.run}`} className="answer ok">
          <p className="label">run {p.run} · passed</p>
          <pre>{p.answer || '(empty answer)'}</pre>
        </div>
      ))}
      {fails.map((x) => (
        <div key={`f${x.run}`} className="answer no">
          <p className="label">run {x.run} · failed</p>
          <pre>{x.answer || '(empty answer)'}</pre>
          <p className="reason">validator: {x.reason}</p>
        </div>
      ))}
    </details>
  );
}
