import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { type Trace, type TraceBlock, fmtDur, fmtInt, fmtUsd, useGet } from '../lib/api';
import { Waterfall } from '../lib/runs';
import { Loading } from '../lib/ui';
import { apiTrialPath, questionPath, runPath } from '../lib/url';

function Block({ b }: { b: TraceBlock }) {
  if (b.type === 'text') return <p className="wrap-any">{b.text}</p>;
  if (b.type === 'thinking')
    return (
      <details>
        <summary className="small muted">thinking ({(b.thinking ?? '').length} chars)</summary>
        <p className="small muted wrap-any">{b.thinking}</p>
      </details>
    );
  if (b.type === 'tool_use') {
    const input = b.input ?? {};
    const main = (input.sql ?? input.code ?? input.answer ?? input.table ?? input.path ?? input.term ?? '') as string;
    const rest = Object.entries(input).filter(([k]) => !['sql', 'code', 'answer', 'table', 'path', 'term'].includes(k));
    return (
      <div className="code band">
        <p className="label">
          → {(b.name ?? '').replace('mcp__dab__', '')}
          {rest.length > 0 && ` · ${rest.map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(' ')}`}
        </p>
        <pre>{main}</pre>
      </div>
    );
  }
  if (b.type === 'tool_result')
    return (
      <div className={`code ${b.is_error ? 'err' : ''}`}>
        <p className="label">← result{b.is_error ? ' · error' : ''}</p>
        <pre>{b.content}</pre>
      </div>
    );
  return <p className="small muted">{b.type}</p>;
}

/** One trial: the verdict, the span waterfall MLflow shows (rebuilt from the run folder), the MLflow view itself on request, and the full transcript. */
export function TracePage() {
  const { id = '', ds = '', n = '', t: k = '' } = useParams();
  // the address is the trial's id, `/runs/<run>/deps_dev_v1/1/t1`; the file name stays on disk
  const tid = /^\d+$/.test(n) && /^t\d+$/.test(k) ? `${ds}/${n}/${k}` : null;
  const { data: t, error } = useGet<Trace>(tid ? apiTrialPath(id, tid) : null);
  const [showSystem, setShowSystem] = useState(false);
  const [showMlflow, setShowMlflow] = useState(false);
  if (!tid) return <Loading error={`${ds}/${n}/${k} is not a trial: the address is /runs/<run>/<dataset>/<n>/t<k>`} />;
  if (!t) return <Loading error={error} />;
  const system = t.trace.find((e) => e.role === 'system');
  const user = t.trace.find((e) => e.role === 'user');
  const turns = t.trace.filter((e) => e.role === 'assistant' || e.role === 'tool');
  const errors = t.tool_calls.filter((c) => c.error).length;
  const tools = t.spans.filter((s) => s.kind === 'tool');
  const toolS = tools.reduce((s, x) => s + (x.end - x.start), 0);
  const verdict = t.passed == null ? 'not scored' : t.passed ? 'pass' : 'fail';
  return (
    <>
      <p className="label">
        <Link to="/runs">runs</Link> · <Link to={runPath(id)}>{id}</Link> · <Link to={runPath(id, { q: ds })}>{ds}</Link> · <Link to={runPath(id, { q: `${ds}/${n}` })}>{n}</Link> · {k}
      </p>
      <h1>
        <Link to={questionPath(t.query_id)}>{t.query_id}</Link> trial {t.trial}: <em>{verdict}</em> — {t.n_turns || t.spans.filter((s) => s.kind === 'turn').length} turns, {t.tool_calls.length} tool calls, {fmtDur(t.duration_ms)}, {fmtUsd(t.cost_usd, 3)}
        {t.error && ` — ${t.error}`}
      </h1>
      <p className="lead">
        <code>{t.model}</code> at effort <code>{t.effort}</code>; the system prompt is {fmtInt(t.system_prompt_chars)} characters (behaviour + the <code>{t.dataset}</code> pack at <code>{t.context_sha}</code>). Tokens:{' '}
        {fmtInt(t.input_tokens + t.cache_creation_tokens)} fresh input, {fmtInt(t.cache_read_tokens)} cache read, {fmtInt(t.output_tokens)} output.{' '}
        {errors > 0 && `${errors} tool call${errors === 1 ? '' : 's'} returned an error. `}
        {t.mlflow_trace_url ? (
          <>
            The same trace in MLflow: <a href={t.mlflow_trace_url}>{t.mlflow_trace_id}</a>.
          </>
        ) : (
          'Not logged to MLflow (run with --no-mlflow, or tracking was down).'
        )}
      </p>
      <div className="compare">
        <div className={`answer ${t.passed == null ? '' : t.passed ? 'ok' : 'no'}`}>
          <p className="label">answer · judged {verdict} by the query's validate.py</p>
          <pre className="wrap-any">{t.answer || '(none)'}</pre>
          {t.reason && <p className="reason">{t.reason}</p>}
        </div>
        <div className="answer">
          <p className="label">gold · {t.gold ? `${t.gold.lines} line${t.gold.lines === 1 ? '' : 's'}` : 'not in the index'}</p>
          <pre className="wrap-any">{t.gold?.text ?? '—'}</pre>
        </div>
      </div>

      <h2>
        01 · Timeline — {toolS > 0 && t.duration_ms > 0 ? `${Math.round((toolS * 1000 * 100) / t.duration_ms)}% of the ${fmtDur(t.duration_ms)} was inside tools` : 'no tool time recorded'}
        {tools.length > 0 && `, ${tools.filter((x) => x.status === 'ERROR').length} of ${tools.length} tool spans errored`}
      </h2>
      <p>
        The span tree the harness logs to MLflow, rebuilt from the trace file in <code>runs/{id}/traces/</code>: a <code>turn</code> span per assistant message, a tool span per call. Click a span for its input and output.
      </p>
      <Waterfall spans={t.spans} durationS={t.duration_ms / 1000} />
      {t.mlflow_trace_url && !t.mlflow_embeddable && (
        <p className="small muted">
          The MLflow view of this trace is <a href={t.mlflow_trace_url}>one click away</a>; embedding it here needs the central server started with <code>MLFLOW_SERVER_X_FRAME_OPTIONS=NONE</code> (it sends <code>SAMEORIGIN</code> today).
        </p>
      )}
      {t.mlflow_trace_url && t.mlflow_embeddable && (
        <>
          <div className="filters">
            <button type="button" className={`tog ${showMlflow ? 'on' : ''}`} onClick={() => setShowMlflow((v) => !v)}>
              {showMlflow ? 'Hide the MLflow trace view' : 'Show the MLflow trace view'}
            </button>
            <span className="count">
              embedded from <a href={t.mlflow_trace_url}>{t.mlflow_trace_url.replace(/^https?:\/\//, '').split('/#')[0]}</a>
            </span>
          </div>
          {showMlflow && <iframe className="mlflow" src={t.mlflow_trace_url} title={`MLflow trace ${t.mlflow_trace_id}`} />}
        </>
      )}

      <h2>02 · Transcript — the system prompt, the question, every turn and every tool exchange</h2>
      <div className="filters">
        <button type="button" className={`tog ${showSystem ? 'on' : ''}`} onClick={() => setShowSystem((v) => !v)}>
          {showSystem ? 'Hide the system prompt' : 'Show the system prompt'}
        </button>
      </div>
      {showSystem && system && (
        <div className="code band">
          <p className="label">system · {fmtInt(t.system_prompt_chars)} chars</p>
          <pre>{typeof system.content === 'string' ? system.content : ''}</pre>
        </div>
      )}
      <div className="code">
        <p className="label">user</p>
        <pre>{user && typeof user.content === 'string' ? user.content : ''}</pre>
      </div>
      {turns.map((e, i) => (
        <section key={i} className="turn">
          <p className="label">
            {e.role === 'assistant' ? 'assistant' : 'tool results'}
            {e.t != null && ` · ${e.t.toFixed(1)}s`}
          </p>
          {typeof e.content === 'string' ? <p>{e.content}</p> : e.content.map((b, j) => <Block key={j} b={b} />)}
        </section>
      ))}
    </>
  );
}
