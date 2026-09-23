import { useState } from 'react';
import { type DatasetSummary, type Leaderboard as LB, type Stratified, type TrialsIndex, fmtInt, fmtPct, useGet } from '../lib/api';
import { Loading } from '../lib/ui';

export function Leaderboard() {
  const { data: lb, error } = useGet<LB>('/api/leaderboard');
  const { data: t } = useGet<TrialsIndex>('/api/trials');
  const { data: ds } = useGet<DatasetSummary[]>('/api/datasets');
  const [hideTuned, setHideTuned] = useState(false);
  if (!lb) return <Loading error={error} />;
  const rows = lb.overallLeaderboard.filter((r) => !hideTuned || r.promptGroup !== 'benchmark-informed');
  const tuned = lb.overallLeaderboard.filter((r) => r.promptGroup === 'benchmark-informed').length;
  const withAnswers = new Map(lb.answer_files.filter((f) => f.rank != null).map((f) => [f.rank as number, f]));
  const best = lb.overallLeaderboard[0];
  const worst = lb.overallLeaderboard[lb.overallLeaderboard.length - 1];
  const dsByQueries = ds ? [...ds].sort((a, b) => b.n_queries - a.n_queries) : [];
  const mostQueriesDs = dsByQueries[0];
  const fewestQueriesDs = dsByQueries[dsByQueries.length - 1];
  return (
    <>
      <p className="label">leaderboard · {lb.overallLeaderboard.length} entries · site updated {lb.updatedAt}</p>
      <h1>
        {lb.overallLeaderboard.length} entries from {best.passAt1.toFixed(4)} to {worst.passAt1.toFixed(4)} Pass@1; the top {tuned} all used a <em>DAB-tuned</em> prompt
      </h1>
      <p className="lead">
        Straight from the site's <code>docs/data/leaderboards.json</code>. Pass@1 is the mean over datasets of each dataset's mean per-query pass rate. A "tuned prompt" is one built
        from studying the datasets' conventions; hiding those shows what a general-purpose agent reaches. {lb.answer_files.length} entries have their answers here, rescored
        per query: {lb.answer_files.filter((f) => !f.pr).length} committed upstream and {lb.answer_files.filter((f) => f.pr).length} read from their submission PR's branch.
      </p>
      <div className="filters">
        <button type="button" className={`tog ${hideTuned ? 'on' : ''}`} onClick={() => setHideTuned((v) => !v)}>
          {hideTuned ? `Showing ${rows.length} general-purpose entries` : `Hide the ${tuned} tuned-prompt entries`}
        </button>
      </div>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th className="num">#</th>
              <th>Agent</th>
              <th className="num">Pass@1</th>
              <th className="num">Trials</th>
              <th>Tuned</th>
              <th>Date</th>
              <th>Answers here</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const f = withAnswers.get(r.rank);
              return (
                <tr key={r.rank} className={f ? 'pro' : ''}>
                  <td className="num">{r.rank}</td>
                  <td className="sub wrap-any" style={{ whiteSpace: 'normal' }}>
                    {r.prUrl ? <a href={r.prUrl}>{r.agent}</a> : r.agent}
                    <span className="path">{r.team}</span>
                    {r.note && (
                      <details>
                        <summary className="small">submission note</summary>
                        <p className="small">{r.note}</p>
                      </details>
                    )}
                  </td>
                  <td className="num">{r.passAt1.toFixed(4)}</td>
                  <td className="num">{r.trials}</td>
                  <td>{r.promptGroup === 'benchmark-informed' ? 'yes' : 'no'}</td>
                  <td className="mono">{r.date}</td>
                  <td className="small">
                    {f ? (
                      <>
                        {fmtInt(f.rows)} rows · macro {fmtPct(t?.per_file[f.name]?.macro ?? null, 2)}
                      </>
                    ) : (
                      '—'
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <h2>The {lb.answer_files.length} answer files, rescored here</h2>
      <p>
        Each file's rows were judged by the validators at the ingested commit. A file read from a PR is a reference: it is compared on the Runs tab but kept out of each
        query's pooled published rate, which stays the public baselines' number. "Macro" is the site's Pass@1 definition; "micro" is over rows. They differ because dataset query counts
        vary{mostQueriesDs && fewestQueriesDs && mostQueriesDs.key !== fewestQueriesDs.key
          ? ` — ${mostQueriesDs.key} has ${mostQueriesDs.n_queries} queries and ${fewestQueriesDs.key} has ${fewestQueriesDs.n_queries}`
          : ''}.
      </p>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>File</th>
              <th className="num">Rank</th>
              <th className="num">Rows</th>
              <th className="num">Queries</th>
              <th className="num">Runs / query</th>
              <th className="num">Site Pass@1</th>
              <th className="num">Ours, macro</th>
              <th className="num">Ours, micro</th>
            </tr>
          </thead>
          <tbody>
            {lb.answer_files.map((f) => {
              const pf = t?.per_file[f.name];
              return (
                <tr key={f.name}>
                  <td className="sub">
                    {f.label}
                    <span className="path">
                      {f.upstream_path}
                      {f.pr_url && (
                        <>
                          {' · '}
                          <a href={f.pr_url} target="_blank" rel="noreferrer">
                            PR #{f.pr} @ {f.commit?.slice(0, 7)}
                          </a>
                        </>
                      )}
                    </span>
                  </td>
                  <td className="num">{f.rank ?? '—'}</td>
                  <td className="num">{fmtInt(f.rows)}</td>
                  <td className="num">{f.queries}</td>
                  <td className="num">{f.runs_per_query.join('/')}</td>
                  <td className="num">{f.pass_at_1_site != null ? f.pass_at_1_site.toFixed(4) : '—'}</td>
                  <td className="num">{pf?.macro != null ? pf.macro.toFixed(4) : 'not scored'}</td>
                  <td className="num">{pf?.micro != null ? pf.micro.toFixed(4) : 'not scored'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <StratTable title="Per dataset, the five ReAct baselines (50 trials per query)" s={lb.baselineStratified} scale={1} t={t} table="baselineStratified" />
      <StratTable title="Per dataset, the three PromptQL runs (5 trials per query)" s={lb.promptqlStratified} scale={100} t={t} table="promptqlStratified" />

      <h2>Methodology notes from the site</h2>
      {lb.sources.map((s) => (
        <p key={s} className="small">
          {s}
        </p>
      ))}
    </>
  );
}

function StratTable({ title, s, scale, t, table }: { title: string; s: Stratified; scale: number; t: TrialsIndex | null; table: string }) {
  // our per-dataset macro for the file that carries this column, if rescored
  const ours = (col: string, ds: string): number | null => {
    if (!t) return null;
    const entry = Object.entries(t.site_check.files).find(([, c]) => c.table === table && c.column === col);
    return entry ? (entry[1].per_dataset[ds]?.ours ?? null) : null;
  };
  return (
    <>
      <h2>{title}</h2>
      <div className="tw">
        <table>
          <caption>Site numbers, with our rescore in brackets where it differs by more than half a point</caption>
          <thead>
            <tr>
              <th>Dataset</th>
              {s.columns.map((c) => (
                <th key={c.key} className="num">
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {s.rows.map((r) => (
              <tr key={String(r.dataset)}>
                <td className="sub">{String(r.dataset)}</td>
                {s.columns.map((c) => {
                  const site = Number(r[c.key]) / scale;
                  const o = ours(c.key, String(r.dataset));
                  const diff = o != null && Math.abs(o - site) > 0.005;
                  return (
                    <td key={c.key} className="num">
                      {site.toFixed(2)}
                      {diff ? <span className="v-warn"> [{o!.toFixed(2)}]</span> : ''}
                    </td>
                  );
                })}
              </tr>
            ))}
            <tr className="pro">
              <td className="sub">{String(s.overall.dataset ?? 'Overall')}</td>
              {s.columns.map((c) => (
                <td key={c.key} className="num">
                  {(Number(s.overall[c.key]) / scale).toFixed(4)}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </>
  );
}
