import { Link } from 'react-router-dom';
import { type RunSummary, fmtDur, fmtPct, fmtUsd, useGet } from '../lib/api';
import { Kpi, Loading, Rate } from '../lib/ui';

/** Our own evals: one row per run folder under runs/. Nothing here is read from MLflow. */
export function Runs() {
  const { data: runs, error } = useGet<RunSummary[]>('/api/runs');
  if (!runs) return <Loading error={error} />;
  const live = runs.filter((r) => !r.dry_run && r.scored);
  const best = live.reduce<RunSummary | null>((b, r) => (b == null || (r.pass_rate_macro ?? -1) > (b.pass_rate_macro ?? -1) ? r : b), null);
  const spent = live.reduce((s, r) => s + (r.cost_usd ?? 0), 0);
  const trials = live.reduce((s, r) => s + (r.n ?? 0), 0);
  return (
    <>
      <p className="label">runs · {runs.length} on this machine</p>
      <h1>
        {live.length} scored run{live.length === 1 ? '' : 's'}, {trials} trials, <em>{fmtUsd(spent)}</em> — the best macro Pass@1 so far is{' '}
        {best ? `${fmtPct(best.pass_rate_macro)} (${best.agent}, ${best.split})` : 'not scored yet'}
      </h1>
      <p className="lead">
        Each run is a folder under <code>runs/</code>: <code>run.json</code>, <code>results.jsonl</code> (one row per query × trial, judged by the query's own{' '}
        <code>validate.py</code>), <code>traces/</code>, the agent's files and the composed per-dataset system prompts. The same run is logged to the central MLflow
        (experiment <code>dataagentbench/evals</code>) with one trace per trial; the links open it there. A pass rate is always shown with its denominator; a dry run
        scores nothing.
      </p>
      <div className="kpis">
        <Kpi n={String(runs.length)} b="run folders" />
        <Kpi n={String(trials)} b="scored trials across live runs" />
        <Kpi n={fmtUsd(spent)} b="derived cost, all live runs (Agent SDK cost_usd)" />
        <Kpi n={best ? fmtPct(best.pass_rate_macro) : '—'} b="best macro Pass@1 (mean over datasets)" tone={best ? 'ok' : undefined} />
      </div>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>Run</th>
              <th>Agent</th>
              <th>Split</th>
              <th>Model</th>
              <th className="num">Trials</th>
              <th>Pass (micro)</th>
              <th className="num">Macro</th>
              <th className="num">Cost</th>
              <th className="num">Wall</th>
              <th className="num">Errors</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.run_id} className={r.dry_run ? 'dim' : r.run_id === best?.run_id ? 'pro' : ''}>
                <td className="sub">
                  <Link to={`/runs/${r.run_id}`} className="mono">
                    {r.run_id}
                  </Link>
                  <span className="path">
                    {r.started_at.slice(0, 16).replace('T', ' ')} · {r.hints ? 'hints on' : 'no hints'}
                    {r.challenger_of ? ` · challenger of ${r.challenger_of}` : ''}
                  </span>
                </td>
                <td className="mono">
                  {r.agent}@{r.fingerprint}
                </td>
                <td>
                  {r.split} · {r.n_queries} q
                </td>
                <td className="mono">
                  {r.model.replace('claude-', '')} @ {r.effort}
                </td>
                <td className="num">{r.trials}</td>
                <td>{r.dry_run ? <span className="muted">dry run</span> : <Rate passed={r.passed} n={r.scored} />}</td>
                <td className="num mono">{r.dry_run ? '—' : fmtPct(r.pass_rate_macro)}</td>
                <td className="num mono">{fmtUsd(r.cost_usd)}</td>
                <td className="num mono">{fmtDur(r.duration_ms)}</td>
                <td className="num mono">{r.errors ?? 0}</td>
                <td className="wrap-any small">{r.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {runs.length === 0 && <p className="empty">No runs yet. `make eval` writes the first one; a dry run (`dab eval --dry-run --no-mlflow`) needs no model.</p>}
    </>
  );
}
