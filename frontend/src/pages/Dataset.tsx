import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { type DatasetDetail, fmtBytes, fmtPct, useGet } from '../lib/api';
import { QueryTable } from '../lib/queries';
import { DatasetChips, Loading } from '../lib/ui';
import { questionPath } from '../lib/url';

export function Dataset() {
  const { key } = useParams();
  const { data: d, error } = useGet<DatasetDetail>(key ? `/api/datasets/${key}` : null);
  const [showHints, setShowHints] = useState(false);
  if (!d) return <Loading error={error} />;
  const rows = d.query_rows.slice().sort((a, b) => (a.trials?.rate ?? 1) - (b.trials?.rate ?? 1));
  const hardest = rows[0];
  return (
    <>
      <DatasetChips current={d.key} />
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
          Hardest here is <Link to={questionPath(hardest.id)}>{hardest.id}</Link> at {fmtPct(hardest.trials.rate)} of {hardest.trials.n} trials; easiest is{' '}
          <Link to={questionPath(rows[rows.length - 1].id)}>{rows[rows.length - 1].id}</Link> at {fmtPct(rows[rows.length - 1].trials?.rate)}.
        </p>
      )}

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

      <h2>The {d.n_queries} {d.n_queries === 1 ? 'query' : 'queries'}, hardest first</h2>
      <QueryTable rows={d.query_rows} scope={d.key} />
    </>
  );
}
