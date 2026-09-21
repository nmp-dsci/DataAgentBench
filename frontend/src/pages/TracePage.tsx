import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { type Trace, type TraceBlock, fmtDur, fmtInt, fmtUsd, queryPath, useGet } from '../lib/api';
import { Loading } from '../lib/ui';

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

/** One trial's full trace: the composed system prompt, the question, every turn and every tool exchange. */
export function TracePage() {
  const { id, key } = useParams();
  const { data: t, error } = useGet<Trace>(id && key ? `/api/runs/${id}/traces/${key}` : null);
  const [showSystem, setShowSystem] = useState(false);
  if (!t) return <Loading error={error} />;
  const system = t.trace.find((e) => e.role === 'system');
  const user = t.trace.find((e) => e.role === 'user');
  const turns = t.trace.filter((e) => e.role === 'assistant' || e.role === 'tool');
  const errors = t.tool_calls.filter((c) => c.error).length;
  return (
    <>
      <p className="label">
        <Link to="/runs">runs</Link> · <Link to={`/runs/${id}`}>{id}</Link> · {key}
      </p>
      <h1>
        <Link to={queryPath(t.query_id)}>{t.query_id}</Link> trial {t.trial}: <em>{t.n_turns} turns, {t.tool_calls.length} tool calls</em>, {fmtUsd(t.cost_usd, 3)},{' '}
        {fmtDur(t.duration_ms)}
        {t.error && ` — ${t.error}`}
      </h1>
      <p className="lead">
        <code>{t.model}</code> at effort <code>{t.effort}</code>; the system prompt is {fmtInt(t.system_prompt_chars)} characters (behaviour + the <code>{t.dataset}</code> pack at{' '}
        <code>{t.context_sha}</code>). Tokens: {fmtInt(t.input_tokens + t.cache_creation_tokens)} fresh input, {fmtInt(t.cache_read_tokens)} cache read, {fmtInt(t.output_tokens)}{' '}
        output. {errors > 0 && `${errors} tool call${errors === 1 ? '' : 's'} returned an error.`}
      </p>
      <div className="card">
        <h3>Answer</h3>
        <pre className="wrap-any">{t.answer || '(none)'}</pre>
      </div>
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
            {e.role === 'assistant' ? `assistant · turn` : 'tool results'}
            {e.t != null && ` · ${e.t.toFixed(1)}s`}
          </p>
          {typeof e.content === 'string' ? <p>{e.content}</p> : e.content.map((b, j) => <Block key={j} b={b} />)}
        </section>
      ))}
    </>
  );
}
