import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { type DatasetDetail, type DatasetSummary, STYLE_LABEL, fmtBytes, fmtPct, queryPath, useGet } from '../lib/api';
import { Gold, Loading, Rate } from '../lib/ui';

export function Dataset() {
  const { key } = useParams();
  const nav = useNavigate();
  const { data: all } = useGet<DatasetSummary[]>('/api/datasets');
  const { data: d, error } = useGet<DatasetDetail>(key ? `/api/datasets/${key}` : null);
  const [showHints, setShowHints] = useState(false);
  if (!d) return <Loading error={error} />;
  const rows = d.query_rows.slice().sort((a, b) => (a.trials?.rate ?? 1) - (b.trials?.rate ?? 1));
  const hardest = rows[0];
  // Same order as the Datasets cards, so stepping through matches what was on screen there.
  const order = (all ?? []).slice().sort((a, b) => b.n_queries - a.n_queries || a.key.localeCompare(b.key));
  const at = order.findIndex((x) => x.key === d.key);
  const step = (n: number) => order.length > 0 && nav(`/datasets/${order[(at + n + order.length) % order.length].key}`);
  return (
    <>
      <p className="crumbs">
        <Link to="/datasets">Datasets</Link> › {d.key}
      </p>
      <p className="label">
        {d.folder} · {d.n_dbs} databases · {d.engines.join(', ')} · {fmtBytes(d.bytes_total)}
      </p>
      <h1>
        {d.key} — {d.n_queries} {d.n_queries === 1 ? 'query' : 'queries'} over {d.n_dbs} databases
        {d.trials ? `, passed in ${fmtPct(d.trials.rate)} of ${d.trials.n} published trials` : ''}
      </h1>
      {hardest?.trials && (
        <p className="lead">
          Hardest here is <Link to={queryPath(hardest.id)}>{hardest.id}</Link> at {fmtPct(hardest.trials.rate)} of {hardest.trials.n} trials; easiest is{' '}
          <Link to={queryPath(rows[rows.length - 1].id)}>{rows[rows.length - 1].id}</Link> at {fmtPct(rows[rows.length - 1].trials?.rate)}.
        </p>
      )}

      <div className="filters">
        <label className="pick">
          <span className="label">dataset</span>
          <select value={d.key} onChange={(e) => nav(`/datasets/${e.target.value}`)} aria-label="switch dataset">
            {order.map((x) => (
              <option key={x.key} value={x.key}>
                {x.key} — {x.n_queries} {x.n_queries === 1 ? 'query' : 'queries'}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="tog" onClick={() => step(-1)} disabled={order.length < 2} aria-label="previous dataset">
          ‹ prev
        </button>
        <button type="button" className="tog" onClick={() => step(1)} disabled={order.length < 2} aria-label="next dataset">
          next ›
        </button>
        <span className="count">
          {at < 0 ? '—' : at + 1} of {order.length || '…'}
        </span>
      </div>

      <h2>The databases an agent must join</h2>
      <div className="tw">
        <table>
          <caption>
            From <code>{d.folder}/db_config.yaml</code>; sizes from <code>dataset_manifest.tsv</code> (or the file in git when not listed there)
          </caption>
          <thead>
            <tr>
              <th>Client</th>
              <th>Engine</th>
              <th>File or database</th>
              <th className="num">Bytes</th>
            </tr>
          </thead>
          <tbody>
            {d.dbs.map((db) => (
              <tr key={db.name}>
                <td className="sub">{db.name}</td>
                <td className="mono">{db.engine}</td>
                <td className="mono wrap-any">
                  {db.file ?? String(db.config.db_name ?? '')}
                  {db.config.db_name && db.file ? <span className="path">pg/mongo db: {String(db.config.db_name)}</span> : null}
                </td>
                <td className="num">{fmtBytes(db.bytes)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>The description every agent reads, and the hints some used</h2>
      <p>
        <code>db_description.txt</code> is {fmtBytes(d.description_bytes)}; the hint file is {d.hints_bytes ? fmtBytes(d.hints_bytes) : 'absent'} and is appended to it when an agent runs
        with <code>--use_hints</code> (the leaderboard's "Hints ✓").
      </p>
      <div className="filters">
        <button type="button" className={`tog ${showHints ? 'on' : ''}`} onClick={() => setShowHints((v) => !v)} disabled={!d.hints}>
          {showHints ? 'Hide hints' : 'Show hints'}
        </button>
      </div>
      <div className="grid2">
        <div className="code">
          <p className="label">db_description.txt</p>
          <pre>{d.description}</pre>
        </div>
        {showHints && (
          <div className="code band">
            <p className="label">db_description_withhint.txt</p>
            <pre>{d.hints}</pre>
          </div>
        )}
      </div>

      <h2>The {d.n_queries} queries, hardest first</h2>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>Query</th>
              <th>Question</th>
              <th>Gold</th>
              <th>Validator</th>
              <th>Published pass rate</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((q) => (
              <tr key={q.id}>
                <td className="sub">
                  <Link to={queryPath(q.id)}>{q.id}</Link>
                </td>
                <td className="q wrap">
                  {q.question.length > 220 ? `${q.question.slice(0, 220)}…` : q.question}
                  {q.footnote && <span className="tag warn" style={{ marginLeft: 'var(--s2)' }}>revised</span>}
                </td>
                <td className="pre">
                  <Gold preview={q.gold_preview} lines={q.gold_lines} />
                </td>
                <td>{STYLE_LABEL[q.validator_style] ?? q.validator_style}</td>
                <td>
                  <Rate passed={q.trials?.passed} n={q.trials?.n} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
