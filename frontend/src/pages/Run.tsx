import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ROLE_LABEL, type RunDetail, type TrialRow, fmtDur, fmtInt, fmtPct, fmtSec, fmtTok, fmtUsd, traceKey, useGet } from '../lib/api';
import { Delta, ProfileTable, Ratios, QueryCell, Role, TrialBars } from '../lib/runs';
import { Kpi, Loading, Rate } from '../lib/ui';

type Filter = 'all' | 'failed' | 'timeouts';
type Sort = 'query' | 'cost' | 'turns' | 'tokens' | 'wall';

/** One run: its verdict against the champion, its production profile with the tail, every dataset, every trial with its trace. */
export function Run() {
  const { id } = useParams();
  const { data: run, error } = useGet<RunDetail>(id ? `/api/runs/${id}` : null);
  const [filter, setFilter] = useState<Filter>('all');
  const [sort, setSort] = useState<Sort>('query');
  if (!run) return <Loading error={error} />;
  const rows = run.results;
  const p = run.profile;
  const vs = run.versus;
  const tokens = (r: TrialRow) => r.input_tokens + r.cache_creation_tokens + r.cache_read_tokens + r.output_tokens;
  const shown = rows
    .filter((r) => (filter === 'failed' ? r.passed === false : filter === 'timeouts' ? r.timed_out : true))
    .sort((a, b) => (sort === 'cost' ? (b.cost_usd ?? 0) - (a.cost_usd ?? 0) : sort === 'turns' ? b.n_turns - a.n_turns : sort === 'tokens' ? tokens(b) - tokens(a) : sort === 'wall' ? b.duration_ms - a.duration_ms : a.query_id.localeCompare(b.query_id) || a.trial - b.trial));
  const perDs = Object.entries(run.per_dataset ?? {}).sort(([a], [b]) => a.localeCompare(b));
  const failed = rows.filter((r) => r.passed === false);
  const tail = p.metrics.cost_usd.p50 > 0 ? p.metrics.cost_usd.p95 / p.metrics.cost_usd.p50 : 0;
  return (
    <>
      <p className="label">
        <Link to="/runs">runs</Link> · {run.run_id} · <Role role={run.role} />
      </p>
      <h1>
        {ROLE_LABEL[run.role][0].toUpperCase() + ROLE_LABEL[run.role].slice(1)} {run.agent}@{run.fingerprint} on {run.split} ({run.n_queries} × {run.trials}):{' '}
        <em>{run.dry_run ? 'dry run, nothing scored' : `${run.passed ?? 0}/${run.scored ?? 0} pass, macro ${fmtPct(run.pass_rate_macro)}`}</em>
        {vs && !run.dry_run && (
          <>
            {' '}
            — <Delta v={run.pass_rate_macro} base={vs.pass_rate_macro} fmt="pct" /> against the champion
          </>
        )}
      </h1>
      <p className="lead">
        <code>{run.model}</code> at effort <code>{run.effort}</code>, {run.workers} workers, max {run.max_turns} turns, hints {run.hints ? 'on' : 'off'}. Context pack <code>{run.context_sha}</code>, code <code>{run.code_sha.slice(0, 7)}</code>,
        upstream <code>{run.upstream_commit.slice(0, 7)}</code>. {fmtUsd(run.cost_usd)} in total, {fmtDur(run.duration_ms)} of trial time summed.{run.note && ` Note: ${run.note}`}{' '}
        {run.mlflow_url && (
          <>
            MLflow: <a href={run.mlflow_url}>run {run.mlflow_run_id?.slice(0, 8)}</a>.
          </>
        )}
        {vs && (
          <>
            {' '}
            Measured against the champion{' '}
            <Link to={`/runs/${vs.run_id}`} className="mono">
              {vs.run_id}
            </Link>
            {vs.split !== run.split && ` (a different split: ${vs.split}, ${vs.n_queries} queries — the Δs below are indicative only)`}.
          </>
        )}
      </p>
      <div className="kpis">
        <Kpi n={run.dry_run ? '—' : `${fmtPct(run.pass_rate_macro)} · ${run.passed}/${run.scored}`} b={vs ? `macro Pass@1 · micro; champion ${fmtPct(vs.pass_rate_macro)} · ${vs.passed}/${vs.scored}` : 'macro Pass@1 (mean over datasets) · micro pass'} tone={run.role === 'champion' ? 'ok' : undefined} />
        <Kpi n={`${fmtUsd(p.metrics.cost_usd.p50, 2)} / ${fmtUsd(p.metrics.cost_usd.p95, 2)}`} b={`cost per trial, p50 / p95${vs ? ` · champion ${fmtUsd(vs.profile.metrics.cost_usd.p50, 2)} / ${fmtUsd(vs.profile.metrics.cost_usd.p95, 2)}` : ''}`} />
        <Kpi n={`${p.metrics.turns.p50} / ${p.metrics.turns.p95}`} b={`turns per trial, p50 / p95${vs ? ` · champion ${vs.profile.metrics.turns.p50} / ${vs.profile.metrics.turns.p95}` : ''}`} />
        <Kpi n={`${fmtTok(p.metrics.total.p50)} / ${fmtTok(p.metrics.total.p95)}`} b={`total tokens per trial, p50 / p95${vs ? ` · champion ${fmtTok(vs.profile.metrics.total.p50)} / ${fmtTok(vs.profile.metrics.total.p95)}` : ''}`} />
        <Kpi n={`${fmtSec(p.metrics.wall_s.p50)} / ${fmtSec(p.metrics.wall_s.p95)}`} b={`wall time per trial, p50 / p95${vs ? ` · champion ${fmtSec(vs.profile.metrics.wall_s.p50)} / ${fmtSec(vs.profile.metrics.wall_s.p95)}` : ''}`} />
        <Kpi n={`${p.timeout_rate ? fmtPct(p.timeout_rate) : '0%'} · ${run.errors ?? 0}`} b={`timed out · errored, of ${p.n} trials that ran`} tone={p.timeout_rate || run.errors ? 'warn' : undefined} />
      </div>

      <h2>
        01 · Profile — {tail >= 3 ? `the p95 trial costs ${tail.toFixed(0)}× the median; the tail is ${p.exhausted ? 'the trials that ran out' : 'a few long trials'}` : 'a flat distribution, the median and the p95 trial cost about the same'}
      </h2>
      <Ratios p={p} />
      <TrialBars rows={rows} runId={run.run_id} />
      <ProfileTable p={p} versus={vs?.profile} />

      {perDs.length > 0 && (
        <>
          <h2>
            02 · Datasets — {perDs.filter(([, v]) => (v.rate ?? 0) === 0).length} of {perDs.length} never pass{vs ? ', each against the champion' : ''}
          </h2>
          <div className="tw">
            <table>
              <thead>
                <tr>
                  <th>Dataset</th>
                  <th className="num">Queries</th>
                  <th>Pass</th>
                  <th className="num">Macro (mean per-query rate)</th>
                  {vs && <th className="num">Champion</th>}
                  {vs && <th className="num">Δ</th>}
                </tr>
              </thead>
              <tbody>
                {perDs.map(([ds, v]) => (
                  <tr key={ds} className={(v.rate ?? 0) === 0 ? 'warnrow' : ''}>
                    <td className="sub">
                      <Link to={`/datasets/${ds}`}>{ds}</Link>
                    </td>
                    <td className="num">{v.queries}</td>
                    <td>
                      <Rate passed={v.passed} n={v.n} />
                    </td>
                    <td className="num mono">{fmtPct(v.rate)}</td>
                    {vs && <td className="num mono">{fmtPct(vs.per_dataset?.[ds]?.rate)}</td>}
                    {vs && (
                      <td className="num">
                        <Delta v={v.rate} base={vs.per_dataset?.[ds]?.rate} fmt="pct" />
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h2>
        03 · Trials — {rows.length} rows, {failed.length} failed, {rows.filter((r) => r.timed_out).length} timed out, {rows.filter((r) => r.rate_limited).length} rate-limited
      </h2>
      <div className="filters">
        {(['all', 'failed', 'timeouts'] as const).map((f) => (
          <button key={f} type="button" className={`tog ${filter === f ? 'on' : ''}`} onClick={() => setFilter(f)}>
            {f === 'all' ? 'every trial' : f === 'failed' ? 'failed only' : 'timed out only'}
          </button>
        ))}
        <select value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="sort trials">
          <option value="query">sort by query</option>
          <option value="cost">most expensive first</option>
          <option value="turns">most turns first</option>
          <option value="tokens">most tokens first</option>
          <option value="wall">slowest first</option>
        </select>
        <span className="count">
          {shown.length} of {rows.length}
        </span>
      </div>
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
            {shown.map((r: TrialRow) => (
              <tr key={`${r.query_id}-${r.trial}`} className={r.passed === false ? 'warnrow' : r.rate_limited ? 'dim' : ''}>
                <QueryCell id={r.query_id} question={r.question} />
                <td className="num">{r.trial}</td>
                <td>
                  {r.passed == null ? <span className="tag">{r.rate_limited ? 'rate limited' : 'not scored'}</span> : r.passed ? <span className="tag ok">pass</span> : <span className="tag warn">{r.timed_out ? 'fail · timed out' : r.terminal_reason === 'max_turns' ? 'fail · max turns' : 'fail'}</span>}
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
