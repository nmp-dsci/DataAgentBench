import { Link, useParams } from 'react-router-dom';
import { type RunDetail, type TrialRow, fmtDur, fmtInt, fmtPct, fmtUsd, queryPath, traceKey, useGet } from '../lib/api';
import { Kpi, Loading, Rate } from '../lib/ui';

function pct(values: number[], p: number): number {
  if (!values.length) return 0;
  const v = [...values].sort((a, b) => a - b);
  return v[Math.min(v.length - 1, Math.round(p * (v.length - 1)))];
}

/** One run: its per-dataset rates, every trial with a link to its trace, and the token profile. */
export function Run() {
  const { id } = useParams();
  const { data: run, error } = useGet<RunDetail>(id ? `/api/runs/${id}` : null);
  if (!run) return <Loading error={error} />;
  const rows = run.results;
  const scored = rows.filter((r) => r.passed != null);
  const turns = rows.map((r) => r.n_turns);
  const fresh = rows.map((r) => r.input_tokens + r.cache_creation_tokens);
  const reads = rows.map((r) => r.cache_read_tokens);
  const outs = rows.map((r) => r.output_tokens);
  const costs = rows.map((r) => r.cost_usd ?? 0);
  const perDs = Object.entries(run.per_dataset ?? {}).sort(([a], [b]) => a.localeCompare(b));
  const failed = scored.filter((r) => r.passed === false);
  return (
    <>
      <p className="label">
        <Link to="/runs">runs</Link> · {run.run_id}
      </p>
      <h1>
        {run.agent}@{run.fingerprint} on {run.split}: <em>{run.dry_run ? 'dry run, nothing scored' : `${run.passed ?? 0}/${run.scored ?? 0} pass`}</em>
        {!run.dry_run && `, macro ${fmtPct(run.pass_rate_macro)}`} · {fmtUsd(run.cost_usd)} · {fmtDur(run.duration_ms)}
      </h1>
      <p className="lead">
        {run.n_queries} queries × {run.trials} trial{run.trials === 1 ? '' : 's'} on <code>{run.model}</code> at effort <code>{run.effort}</code>, {run.workers} workers, max{' '}
        {run.max_turns} turns, hints {run.hints ? 'on' : 'off'}. Context pack <code>{run.context_sha}</code>, code <code>{run.code_sha.slice(0, 7)}</code>, upstream{' '}
        <code>{run.upstream_commit.slice(0, 7)}</code>.{run.note && ` Note: ${run.note}`}{' '}
        {run.mlflow_url && (
          <>
            MLflow: <a href={run.mlflow_url}>run {run.mlflow_run_id?.slice(0, 8)}</a>.
          </>
        )}
      </p>
      <div className="kpis">
        <Kpi n={`${pct(turns, 0.5)} / ${pct(turns, 0.9)}`} b="turns per trial, p50 / p90" />
        <Kpi n={`${fmtInt(pct(fresh, 0.5))} / ${fmtInt(pct(reads, 0.5))}`} b="tokens per trial, p50: fresh input / cache read" />
        <Kpi n={fmtInt(pct(outs, 0.5))} b="output tokens per trial, p50" />
        <Kpi n={`${fmtUsd(pct(costs, 0.5), 3)} / ${fmtUsd(pct(costs, 0.9), 3)}`} b="cost per trial, p50 / p90 (SDK cost_usd)" />
      </div>
      {perDs.length > 0 && (
        <div className="tw">
          <table>
            <thead>
              <tr>
                <th>Dataset</th>
                <th className="num">Queries</th>
                <th>Pass</th>
                <th className="num">Macro (mean per-query rate)</th>
              </tr>
            </thead>
            <tbody>
              {perDs.map(([ds, v]) => (
                <tr key={ds}>
                  <td className="sub">
                    <Link to={`/datasets/${ds}`}>{ds}</Link>
                  </td>
                  <td className="num">{v.queries}</td>
                  <td>
                    <Rate passed={v.passed} n={v.n} />
                  </td>
                  <td className="num mono">{fmtPct(v.rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h2>
        {rows.length} trials{failed.length ? `, ${failed.length} failed` : ''}
      </h2>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>Query</th>
              <th className="num">t</th>
              <th>Verdict</th>
              <th>Answer</th>
              <th className="num">Turns</th>
              <th className="num">Tools</th>
              <th className="num">Fresh in</th>
              <th className="num">Cache read</th>
              <th className="num">Out</th>
              <th className="num">Cost</th>
              <th className="num">Wall</th>
              <th>Trace</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r: TrialRow) => (
              <tr key={`${r.query_id}-${r.trial}`} className={r.passed === false ? 'warnrow' : ''}>
                <td className="sub">
                  <Link to={queryPath(r.query_id)} className="mono">
                    {r.query_id}
                  </Link>
                  <span className="path wrap-any">{r.question.slice(0, 90)}</span>
                </td>
                <td className="num">{r.trial}</td>
                <td>
                  {r.passed == null ? <span className="tag">{r.rate_limited ? 'rate limited' : 'not scored'}</span> : r.passed ? <span className="tag ok">pass</span> : <span className="tag warn">fail</span>}
                  {r.error && <span className="path wrap-any">{r.error.slice(0, 80)}</span>}
                  {!r.passed && r.reason && <span className="path wrap-any">{r.reason.slice(0, 120)}</span>}
                </td>
                <td className="answer mono small">{r.answer.slice(0, 160)}</td>
                <td className="num">{r.n_turns}</td>
                <td className="num">{r.tool_calls}</td>
                <td className="num mono">{fmtInt(r.input_tokens + r.cache_creation_tokens)}</td>
                <td className="num mono">{fmtInt(r.cache_read_tokens)}</td>
                <td className="num mono">{fmtInt(r.output_tokens)}</td>
                <td className="num mono">{fmtUsd(r.cost_usd, 3)}</td>
                <td className="num mono">{fmtDur(r.duration_ms)}</td>
                <td>
                  {r.trace_file && (
                    <Link to={`/runs/${run.run_id}/traces/${traceKey(r)}`} className="mono">
                      trace
                    </Link>
                  )}
                  {r.mlflow_trace_url && (
                    <>
                      {' · '}
                      <a href={r.mlflow_trace_url} className="mono">
                        mlflow
                      </a>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
