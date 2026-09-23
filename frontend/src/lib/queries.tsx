import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { type QuerySummary, STYLE_LABEL, fmtInt, fmtPct, queryPath, useGet } from './api';
import { Gold, Rate } from './ui';

type SortKey = 'rate' | 'id' | 'gold' | 'best';

/** Every query in `rows`, filterable and sortable. `scope` is the dataset the caller already
 *  narrowed to: it names that in the caption and drops the dataset select, which would be a
 *  list of one. Both dataset pages share this, so the columns can never drift apart. */
export function QueryTable({ rows: all, scope }: { rows: QuerySummary[]; scope?: string }) {
  const [dataset, setDataset] = useState('all');
  const [style, setStyle] = useState('all');
  const [shape, setShape] = useState<'all' | 'single' | 'list'>('all');
  const [q, setQ] = useState('');
  const [sort, setSort] = useState<SortKey>('rate');
  const [asc, setAsc] = useState(true);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const out = all.filter(
      (x) =>
        (scope || dataset === 'all' || x.dataset_key === dataset) &&
        (style === 'all' || x.validator_style === style) &&
        (shape === 'all' || (shape === 'single' ? x.gold_lines === 1 : x.gold_lines > 1)) &&
        (!needle || x.question.toLowerCase().includes(needle) || x.id.includes(needle) || x.gold_text.toLowerCase().includes(needle)),
    );
    const key = (x: QuerySummary): number | string => {
      if (sort === 'rate') return x.trials?.rate ?? 2;
      if (sort === 'best') return x.trials?.best_rate ?? 2;
      if (sort === 'gold') return x.gold_lines;
      return x.id;
    };
    out.sort((a, b) => {
      const ka = key(a);
      const kb = key(b);
      const c = typeof ka === 'number' && typeof kb === 'number' ? ka - kb : String(ka).localeCompare(String(kb), undefined, { numeric: true });
      return asc ? c : -c;
    });
    return out;
  }, [all, scope, dataset, style, shape, q, sort, asc]);

  const datasets = Array.from(new Set(all.map((x) => x.dataset_key))).sort();
  const scored = all.filter((x) => x.trials);

  const th = (k: SortKey, label: string, cls = '') => (
    <th
      className={`sortable ${cls} ${sort === k ? 'sorted' : ''}`}
      onClick={() => {
        if (sort === k) setAsc((v) => !v);
        else {
          setSort(k);
          setAsc(k === 'id');
        }
      }}
    >
      {label} {sort === k ? (asc ? '↑' : '↓') : ''}
    </th>
  );

  return (
    <>
      <div className="filters">
        {!scope && (
          <select value={dataset} onChange={(e) => setDataset(e.target.value)} aria-label="dataset">
            <option value="all">all {datasets.length} datasets</option>
            {datasets.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        )}
        <select value={style} onChange={(e) => setStyle(e.target.value)} aria-label="validator style">
          <option value="all">any validator</option>
          {Object.entries(STYLE_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <select value={shape} onChange={(e) => setShape(e.target.value as 'all' | 'single' | 'list')} aria-label="gold shape">
          <option value="all">any gold shape</option>
          <option value="single">single-line gold</option>
          <option value="list">list gold (2+ lines)</option>
        </select>
        <input type="search" placeholder="search question, id or gold" value={q} onChange={(e) => setQ(e.target.value)} aria-label="search" />
        <span className="count">
          {rows.length} of {all.length}
        </span>
      </div>

      <div className="tw">
        <table>
          <thead>
            <tr>
              {th('id', 'Query')}
              {!scope && <th>Dataset</th>}
              <th>Question</th>
              <th>Gold</th>
              {th('gold', 'Lines', 'num')}
              <th>Validator</th>
              {th('rate', 'Published pass rate')}
              {th('best', 'Best file')}
            </tr>
          </thead>
          <tbody>
            {rows.map((x) => (
              <tr key={x.id} className={x.trials && x.trials.passed === 0 ? 'dim' : ''}>
                <td className="sub">
                  <Link to={queryPath(x.id)}>{x.id}</Link>
                  {x.footnote && (
                    <span className="path">
                      <span className="tag warn">gold revised upstream</span>
                    </span>
                  )}
                  {x.site_text_matches === false && (
                    <span className="path">
                      <span className="tag">wording differs from site</span>
                    </span>
                  )}
                </td>
                {!scope && (
                  <td className="sub">
                    <Link to={`/datasets/${x.dataset_key}`}>{x.dataset_key}</Link>
                  </td>
                )}
                <td className="q wrap">{x.question.length > 200 ? `${x.question.slice(0, 200)}…` : x.question}</td>
                <td className="pre">
                  <Gold preview={x.gold_preview} lines={x.gold_lines} full={x.gold_text} />
                </td>
                <td className="num">{x.gold_lines}</td>
                <td>{STYLE_LABEL[x.validator_style] ?? x.validator_style}</td>
                <td>
                  <Rate passed={x.trials?.passed} n={x.trials?.n} />
                </td>
                <td className="mono small">
                  {x.trials?.best_file ? (
                    <>
                      {fmtPct(x.trials.best_rate)} · {x.trials.best_file.replace(/_wiki4_pp2_n5$/, '')}
                    </>
                  ) : (
                    '—'
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="small muted">
        {fmtInt(scored.reduce((n, x) => n + (x.trials?.n ?? 0), 0))} trials across {scored.length} scored {scored.length === 1 ? 'query' : 'queries'}
        {scope ? ` in ${scope}` : ''}. "Best file" is the single answer file with the highest pass rate on that query and its denominator is that file's trials (50 for a ReAct
        baseline, 5 for the others).
      </p>
    </>
  );
}

/** The whole 54 — used by the Datasets index, where no dataset is selected. */
export function useAllQueries() {
  return useGet<QuerySummary[]>('/api/queries');
}
