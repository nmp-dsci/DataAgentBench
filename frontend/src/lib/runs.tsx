import { useState } from 'react';
import { Link } from 'react-router-dom';
import { type Profile, type ProfileKey, ROLE_LABEL, type RunRole, type Span, type TrialRow, fmtInt, fmtPct, fmtSec, fmtTok, fmtUsd, queryPath } from './api';

/** The role word, never colour alone: champion is the accent (shipped), superseded and dry are muted. */
export function Role({ role }: { role: RunRole }) {
  const cls = role === 'champion' ? 'ok' : role === 'challenger' ? 'warn' : role === 'smoke' ? '' : 'no';
  return <span className={`chip role ${cls}`}>{ROLE_LABEL[role]}</span>;
}

/** A signed difference against the champion, tinted by whether it is the good direction. */
export function Delta({ v, base, fmt, lowerIsBetter = false, digits = 0 }: { v: number | null | undefined; base: number | null | undefined; fmt: 'pct' | 'usd' | 'int' | 'tok' | 'sec'; lowerIsBetter?: boolean; digits?: number }) {
  if (v == null || base == null) return <span className="muted">—</span>;
  const d = v - base;
  if (Math.abs(d) < 1e-9) return <span className="mono muted">±0</span>;
  const good = lowerIsBetter ? d < 0 : d > 0;
  const s =
    fmt === 'pct' ? `${(d * 100).toFixed(digits)} pt` : fmt === 'usd' ? fmtUsd(Math.abs(d), digits || 2).replace('$', '$') : fmt === 'tok' ? fmtTok(Math.abs(d)) : fmt === 'sec' ? fmtSec(Math.abs(d)) : Math.abs(d).toFixed(digits);
  return (
    <span className={`mono ${good ? 'v-ok' : 'v-warn'}`}>
      {d > 0 ? '+' : '−'}
      {s.replace(/^-/, '')}
    </span>
  );
}

export const PROFILE_ROWS: { key: ProfileKey; label: string; fmt: (x: number) => string; lowerIsBetter: boolean }[] = [
  { key: 'turns', label: 'turns per trial', fmt: (x) => x.toFixed(x >= 10 ? 0 : 1), lowerIsBetter: true },
  { key: 'tool_calls', label: 'tool calls per trial', fmt: (x) => x.toFixed(x >= 10 ? 0 : 1), lowerIsBetter: true },
  { key: 'wall_s', label: 'wall time per trial', fmt: (x) => fmtSec(x), lowerIsBetter: true },
  { key: 'fresh_in', label: 'fresh input tokens', fmt: (x) => fmtTok(x), lowerIsBetter: true },
  { key: 'cache_read', label: 'cache-read tokens', fmt: (x) => fmtTok(x), lowerIsBetter: true },
  { key: 'output', label: 'output tokens', fmt: (x) => fmtTok(x), lowerIsBetter: true },
  { key: 'total', label: 'total tokens', fmt: (x) => fmtTok(x), lowerIsBetter: true },
  { key: 'cost_usd', label: 'cost per trial', fmt: (x) => fmtUsd(x, 3), lowerIsBetter: true },
];

/** The production profile: every per-trial metric with its mean, median, tail and total; a second column set when there is a champion to measure against. */
export function ProfileTable({ p, versus, versusLabel }: { p: Profile; versus?: Profile | null; versusLabel?: string }) {
  return (
    <div className="tw">
      <table>
        <thead>
          <tr>
            <th>Per trial ({p.n} ran)</th>
            <th className="num">Mean</th>
            <th className="num">p50</th>
            <th className="num">p95</th>
            <th className="num">Max</th>
            <th className="num">Total</th>
            {versus && <th className="num">Δ p50 vs {versusLabel ?? 'champion'}</th>}
            {versus && <th className="num">Δ p95</th>}
          </tr>
        </thead>
        <tbody>
          {PROFILE_ROWS.map((r) => {
            const m = p.metrics[r.key];
            const v = versus?.metrics[r.key];
            return (
              <tr key={r.key}>
                <td className="sub">{r.label}</td>
                <td className="num">{r.fmt(m.mean)}</td>
                <td className="num">{r.fmt(m.p50)}</td>
                <td className="num">{r.fmt(m.p95)}</td>
                <td className="num">{r.fmt(m.max)}</td>
                <td className="num">{r.key === 'cost_usd' ? fmtUsd(m.sum) : r.key === 'wall_s' ? fmtSec(m.sum) : fmtInt(Math.round(m.sum))}</td>
                {versus && (
                  <td className="num">
                    <Delta v={m.p50} base={v?.p50} fmt={r.key === 'cost_usd' ? 'usd' : r.key === 'wall_s' ? 'sec' : r.key === 'turns' || r.key === 'tool_calls' ? 'int' : 'tok'} lowerIsBetter={r.lowerIsBetter} digits={r.key === 'cost_usd' ? 3 : 0} />
                  </td>
                )}
                {versus && (
                  <td className="num">
                    <Delta v={m.p95} base={v?.p95} fmt={r.key === 'cost_usd' ? 'usd' : r.key === 'wall_s' ? 'sec' : r.key === 'turns' || r.key === 'tool_calls' ? 'int' : 'tok'} lowerIsBetter={r.lowerIsBetter} digits={r.key === 'cost_usd' ? 3 : 0} />
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** The ratios that say whether the tail is the agent or the harness. */
export function Ratios({ p }: { p: Profile }) {
  return (
    <div className="chips">
      <span className="chip">cache hit {fmtPct(p.cache_hit_rate)} of input</span>
      <span className="chip">cost per pass {fmtUsd(p.cost_per_pass)}</span>
      <span className="chip">tokens per pass {fmtTok(p.tokens_per_pass)}</span>
      <span className={`chip ${p.timeout_rate ? 'warn' : ''}`}>timeouts {fmtPct(p.timeout_rate)}</span>
      <span className={`chip ${p.error_rate ? 'warn' : ''}`}>errors {fmtPct(p.error_rate)}</span>
      <span className={`chip ${p.exhausted ? 'warn' : ''}`}>{p.exhausted} fail{p.exhausted === 1 ? '' : 's'} by running out</span>
    </div>
  );
}

/** Every trial as one bar, sorted by the chosen metric, coloured by verdict — the shape of the tail at a glance. */
export function TrialBars({ rows, runId }: { rows: TrialRow[]; runId: string }) {
  const [metric, setMetric] = useState<'total' | 'turns' | 'wall' | 'cost'>('total');
  const val = (r: TrialRow) =>
    metric === 'total' ? r.input_tokens + r.cache_creation_tokens + r.cache_read_tokens + r.output_tokens : metric === 'turns' ? r.n_turns : metric === 'wall' ? r.duration_ms / 1000 : (r.cost_usd ?? 0);
  const fmt = (x: number) => (metric === 'total' ? fmtTok(x) : metric === 'turns' ? String(x) : metric === 'wall' ? fmtSec(x) : fmtUsd(x, 2));
  const sorted = [...rows].filter((r) => !r.rate_limited).sort((a, b) => val(b) - val(a));
  const max = Math.max(1, ...sorted.map(val));
  const W = 1000;
  const H = 160;
  const pad = { l: 6, r: 6, t: 8, b: 4 };
  const n = Math.max(1, sorted.length);
  const bw = (W - pad.l - pad.r) / n;
  return (
    <figure>
      <div className="filters">
        <span className="label">Fig · every trial, sorted by</span>
        {(['total', 'turns', 'wall', 'cost'] as const).map((m) => (
          <button key={m} type="button" className={`tog ${metric === m ? 'on' : ''}`} onClick={() => setMetric(m)}>
            {m === 'total' ? 'total tokens' : m === 'wall' ? 'wall time' : m}
          </button>
        ))}
        <span className="count">
          max {fmt(max)} · {sorted.length} trials
        </span>
      </div>
      <svg className="dia" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Every trial of ${runId} as a bar sorted by ${metric}; passed in accent, failed in amber, not scored in grey`}>
        <title>Trials sorted by {metric}</title>
        {sorted.map((r, i) => {
          const h = Math.max(1, ((H - pad.t - pad.b) * val(r)) / max);
          const cls = r.passed == null ? 'bar' : r.passed ? 'bar hi' : 'bar pro';
          return (
            <g key={`${r.query_id}-${r.trial}`} className="pt">
              <title>
                {r.query_id} t{r.trial}: {fmt(val(r))} · {r.passed == null ? 'not scored' : r.passed ? 'pass' : r.timed_out ? 'fail (timed out)' : 'fail'}
              </title>
              <rect className={cls} x={pad.l + i * bw + 0.5} y={H - pad.b - h} width={Math.max(1, bw - 1)} height={h} />
            </g>
          );
        })}
      </svg>
      <figcaption>
        Bars are trials, tallest first; <span className="v-ok">accent</span> passed, <span className="v-warn">amber</span> failed, grey not scored. Hover a bar for the query. Source: <code>runs/{runId}/results.jsonl</code>.
      </figcaption>
    </figure>
  );
}

function fmtSpan(s: number): string {
  return s < 1 ? `${Math.round(s * 1000)}ms` : `${s.toFixed(1)}s`;
}

/** The span waterfall MLflow draws for this trial, from the same span tree, with the selected span's input and output below it. */
export function Waterfall({ spans, durationS }: { spans: Span[]; durationS: number }) {
  const [sel, setSel] = useState<number | null>(null);
  const total = Math.max(durationS, ...spans.map((s) => s.end)) || 1;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * total);
  return (
    <div className="wf" role="list">
      <div className="wf-row wf-head" aria-hidden="true">
        <span className="wf-name label">span</span>
        <span className="wf-track">
          {ticks.map((t) => (
            <span key={t} className="wf-tick label" style={{ left: `${(t / total) * 100}%` }}>
              {t.toFixed(t < 10 ? 1 : 0)}s
            </span>
          ))}
        </span>
        <span className="wf-dur label">dur</span>
      </div>
      {spans.map((sp, i) => {
        const left = (sp.start / total) * 100;
        const width = Math.max(0.3, ((sp.end - sp.start) / total) * 100);
        return (
          <div key={i} role="listitem">
            <button type="button" className={`wf-row wf-${sp.kind} ${sp.status === 'ERROR' ? 'err' : ''} ${sel === i ? 'on' : ''}`} onClick={() => setSel(sel === i ? null : i)} title={`${sp.name}: ${sp.start.toFixed(1)}s → ${sp.end.toFixed(1)}s`}>
              <span className="wf-name mono">
                {sp.kind === 'tool' ? '└ ' : ''}
                {sp.name}
                {sp.status === 'ERROR' && <span className="v-warn"> ✕</span>}
              </span>
              <span className="wf-track">
                <i style={{ left: `${left}%`, width: `${width}%` }} />
              </span>
              <span className="wf-dur mono">{fmtSpan(sp.end - sp.start)}</span>
            </button>
            {sel === i && <SpanDetail s={sp} />}
          </div>
        );
      })}
    </div>
  );
}

function SpanDetail({ s }: { s: Span }) {
  return (
    <div className={`wf-detail ${s.status === 'ERROR' ? 'err' : ''}`}>
      <p className="label">
        {s.kind} · {s.name} · {s.start.toFixed(1)}s → {s.end.toFixed(1)}s{s.status === 'ERROR' ? ' · error' : ''}
        {s.kind === 'turn' && s.thinking_chars ? ` · ${fmtInt(s.thinking_chars)} chars of thinking` : ''}
      </p>
      {s.kind === 'turn' ? (
        <>
          <pre>{s.text || '(no text; this turn only called tools)'}</pre>
          {s.tool_calls && s.tool_calls.length > 0 && <p className="small muted">calls: {s.tool_calls.map((c) => c.replace('mcp__dab__', '')).join(', ')}</p>}
        </>
      ) : (
        <>
          <p className="label">input</p>
          <pre>{Object.entries(s.input ?? {}).map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`).join('\n')}</pre>
          <p className="label">output</p>
          <pre>{s.output || '(empty)'}</pre>
        </>
      )}
    </div>
  );
}

export function TrialLink({ runId, r }: { runId: string; r: TrialRow }) {
  return (
    <Link to={`/runs/${runId}/traces/${r.dataset}_${r.query_id.split('/')[1]}_t${r.trial}`} className="mono">
      trace
    </Link>
  );
}

export function QueryCell({ id, question }: { id: string; question: string }) {
  return (
    <td className="sub">
      <Link to={queryPath(id)} className="mono">
        {id}
      </Link>
      <span className="path wrap-any">{question.slice(0, 90)}</span>
    </td>
  );
}
