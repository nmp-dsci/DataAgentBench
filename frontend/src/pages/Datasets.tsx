import { Link, useNavigate } from 'react-router-dom';
import { type DatasetSummary, type Stats, fmtBytes, fmtInt, fmtPct, useGet } from '../lib/api';
import { DatasetChips, Loading, Rate } from '../lib/ui';

export function Datasets() {
  const { data: ds, error } = useGet<DatasetSummary[]>('/api/datasets');
  const { data: s } = useGet<Stats>('/api/stats');
  const nav = useNavigate();
  if (!ds) return <Loading error={error} />;
  const sorted = ds.slice().sort((a, b) => b.n_queries - a.n_queries || a.key.localeCompare(b.key));
  const bytes = ds.reduce((n, d) => n + d.bytes_total, 0);
  const biggest = sorted[0];
  return (
    <>
      <DatasetChips />
      <p className="label">datasets · {ds.length} in scope</p>
      <h1>
        {ds.length} datasets carry {ds.reduce((n, d) => n + d.n_queries, 0)} queries and {fmtBytes(bytes)} of databases; <em>{biggest.key}</em> alone is {biggest.n_queries} of them
      </h1>
      <p className="lead">
        Each dataset is two to six databases across up to four engines, a schema description the agent reads, an optional hint file, and its queries. The database bytes are
        from the upstream manifest; nothing here downloads them.
      </p>
      <div className="cards">
        {sorted.map((d) => (
          <div key={d.key} className="card link" onClick={() => nav(`/datasets/${d.key}`)} role="link" tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && nav(`/datasets/${d.key}`)}>
            <h3>
              <Link to={`/datasets/${d.key}`}>{d.key}</Link>
            </h3>
            <p className="small">
              {d.n_queries} {d.n_queries === 1 ? 'query' : 'queries'} · {d.n_dbs} DBs · {d.engines.join(', ')} · {fmtBytes(d.bytes_total)}
            </p>
            <p className="small">
              description {fmtBytes(d.description_bytes)} · hints {d.hints_bytes ? fmtBytes(d.hints_bytes) : 'none'}
            </p>
            <p className="small">
              <Rate passed={d.trials?.passed} n={d.trials?.n} />
            </p>
          </div>
        ))}
      </div>
      {s && s.deferred_datasets.length > 0 && (
        <p className="small muted" style={{ marginTop: 'var(--s6)' }}>
          {s.deferred_datasets.length} more datasets with {s.deferred_queries} queries exist upstream and are deferred: {s.deferred_datasets.join(', ')}. Best published pass rate
          among the {ds.length} here: {fmtPct(Math.max(...ds.map((d) => d.trials?.rate ?? 0)))} · trials in total {fmtInt(ds.reduce((n, d) => n + (d.trials?.n ?? 0), 0))}.
        </p>
      )}
    </>
  );
}
