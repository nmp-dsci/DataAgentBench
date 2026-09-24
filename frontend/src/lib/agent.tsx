import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { type GoldDiffLine, type ScoreTotals, type Span, type SpanTokens, fmtInt, fmtTok, fmtUsd } from './api';
import { questionPath, trialId, trialPath } from './url';

// ── shapes served by /api/agents* and /api/agent/tools ────────────────────────
export type AgentRow = { name: string; fingerprint: string; model: string; effort: string | null; max_turns: number; timeout_s: number; exec_timeout_s: number; hints: boolean; pack: boolean; challenger_of: string | null; notes: string[]; tools: string[] };
export type AgentsBoard = { champion: string; versions: AgentRow[] };
export type ToolSpec = { name: string; description: string; schema: { type: string; properties: Record<string, { type: string; description?: string; items?: { type: string } }>; required: string[] }; backend: 'pack' | 'postgres' | 'sandbox' | 'model' | 'state'; calls_model: boolean; playground: 'on' | 'off' | 'echo' };
export type OptimiseSession = { scope: string; notes: string | null; rationale: string; refusals: { notes: string; problems: string[] }[]; questions: string[]; n_turns: number; cost_usd: number | null; error: string | null };
export type OptimiseRecord = { version: string; challenger_of: string; source_run: string; optimiser: { model: string; effort: string }; split: { train: number; heldout: number }; source_scorecard: ScoreTotals; cost_usd: number; sessions: OptimiseSession[]; system_md_changed: boolean };
/** An optimised version's parent, the round that wrote it (agents/<v>/optimise.json) and each changed file. */
export type Lineage = { parent: string; optimise: OptimiseRecord | null; files: { name: string; added: boolean; diff: GoldDiffLine[] }[] };
export type AgentDetail = { name: string; champion: boolean; fingerprint: string; config: Record<string, unknown>; files: Record<string, string>; tools: ToolSpec[]; sandbox_built: boolean; playground_llm: boolean; datasets: string[]; lineage: Lineage | null };
export type PromptResp = { agent: string; dataset: string; hints: boolean; pack: boolean; notes: string; context_sha: string; chars: number; prompt: string };
export type PlayResult = { tool: string; dataset: string; input: Record<string, unknown>; output: string; chars: number; cut: boolean; elapsed_s: number; error: boolean };

export type NodeId = 'question' | 'sdk' | 'prompt' | 'mcp' | 'postgres' | 'sandbox' | 'model' | 'pack' | 'judge' | 'runs' | 'mlflow' | `tool:${string}`;
export type ToolCounts = Record<string, { calls: number; errors: number; p50_ms: number }>;

export function toolCounts(spans: Span[]): ToolCounts {
  const by: Record<string, number[]> = {};
  const errs: Record<string, number> = {};
  for (const s of spans) {
    if (s.kind !== 'tool') continue;
    (by[s.name] ??= []).push((s.end - s.start) * 1000);
    if (s.status === 'ERROR') errs[s.name] = (errs[s.name] ?? 0) + 1;
  }
  const out: ToolCounts = {};
  for (const [name, ms] of Object.entries(by)) {
    const v = [...ms].sort((a, b) => a - b);
    out[name] = { calls: ms.length, errors: errs[name] ?? 0, p50_ms: v[Math.floor((v.length - 1) / 2)] };
  }
  return out;
}

const BACKEND_NODE: Record<ToolSpec['backend'], NodeId | null> = { pack: 'pack', postgres: 'postgres', sandbox: 'sandbox', model: 'model', state: null };

/** The agent system as a graph. Nodes come from the version's config and the tool specs; counts from the selected trace. Hand-laid SVG per DESIGN.md, data-driven content. */
export function AgentGraph({ detail, counts, selected, onSelect, question }: { detail: AgentDetail; counts: ToolCounts | null; selected: NodeId | null; onSelect: (n: NodeId) => void; question: string | null }) {
  const tools = detail.tools;
  const rowH = 30;
  const toolsTop = 16;
  const toolsH = Math.max(tools.length, 8) * rowH;
  const H = Math.max(toolsTop + toolsH + 60, 330);
  const W = 1000;
  const x = { q: 10, sdk: 175, mcp: 435, tool: 585, back: 855 };
  type Backend = { id: NodeId; label: string; sub: string; ext?: boolean };
  const backends = ([
    { id: 'postgres', label: 'Postgres', sub: 'dab_agent · read-only' },
    { id: 'sandbox', label: 'sandbox', sub: detail.sandbox_built ? 'docker · --network none' : 'image not built' },
    { id: 'model', label: 'haiku 4.5', sub: 'llm_extract only', ext: true },
    { id: 'pack', label: 'pack files', sub: 'data/context/' },
  ] as Backend[]).filter((b) => tools.some((t) => BACKEND_NODE[t.backend] === b.id)); // only what this version's tools reach
  const backY: Record<string, number> = {};
  backends.forEach((b, i) => {
    backY[b.id] = toolsTop + 20 + i * 62;
  });
  const cls = (id: NodeId, extra = '') => `nd ${selected === id ? 'hi' : ''} ${extra}`;
  const Node = ({ id, x, y, w, h, label, sub, extra = '', title }: { id: NodeId; x: number; y: number; w: number; h: number; label: string; sub?: string; extra?: string; title: string }) => (
    <g className="pick" role="button" tabIndex={0} aria-label={title} onClick={() => onSelect(id)} onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onSelect(id)}>
      <title>{title}</title>
      <rect className={cls(id, extra)} x={x} y={y} width={w} height={h} rx={6} />
      <text className="tx k" x={x + w / 2} y={y + (sub ? 17 : h / 2 + 5)} textAnchor="middle">
        {label}
      </text>
      {sub && (
        <text className="tx s" x={x + w / 2} y={y + 32} textAnchor="middle">
          {sub}
        </text>
      )}
    </g>
  );
  const model = String(detail.config.model ?? '');
  return (
    <svg className="dia graph" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`The ${detail.name} agent system: question to Agent SDK to the dab MCP server to ${tools.length} tools to their backends, then judge, run folder and MLflow`} style={{ minWidth: 880 }}>
      <defs>
        <marker id="garr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0L10 5L0 10z" fill="currentColor" />
        </marker>
      </defs>
      <Node id="question" x={x.q} y={30} w={140} h={44} label="question" sub={question ? `${question.slice(0, 22)}…` : 'user message'} title="The user message: the benchmark question, nothing else" />
      <Node id="sdk" x={x.sdk} y={16} w={230} h={72} label="Agent SDK" sub={`claude child · ${model} · ≤ ${String(detail.config.max_turns)} turns`} title="The Agent SDK session: a claude child on the subscription" />
      <Node id="prompt" x={x.sdk + 20} y={100} w={190} h={40} label="system prompt" sub="system.md + the dataset pack" title="The composed system prompt for the chosen dataset" />
      <Node id="mcp" x={x.mcp} y={30} w={130} h={44} label='mcp "dab"' sub="in-process · strict" title="One in-process MCP server per trial; no built-in tools" />
      <path className="ed" d={`M${x.q + 140} 52H${x.sdk}`} />
      <path className="ed" d={`M${x.sdk + 230} 52H${x.mcp}`} />
      <path className="ed dash" d={`M${x.sdk + 115} 100V88`} />
      {tools.map((t, i) => {
        const y = toolsTop + i * rowH;
        const c = counts?.[t.name];
        const id: NodeId = `tool:${t.name}`;
        const extra = t.playground === 'off' ? 'warn' : '';
        const back = BACKEND_NODE[t.backend];
        const ty = y + 12;
        return (
          <g key={t.name}>
            <path className={`ed ${c ? 'hi' : 'dash'}`} d={`M${x.mcp + 130} 52 C ${x.mcp + 180} 52, ${x.tool - 40} ${ty}, ${x.tool} ${ty}`} style={c ? { strokeWidth: 1 + Math.min(2, c.calls / 3) } : undefined} />
            <g className="pick" role="button" tabIndex={0} aria-label={`${t.name}: ${t.description}`} onClick={() => onSelect(id)} onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onSelect(id)}>
              <title>
                {t.name} — {t.description}
              </title>
              <rect className={cls(id, extra)} x={x.tool} y={y} width={140} height={24} rx={4} />
              <text className="tx" x={x.tool + 8} y={y + 16}>
                {t.name}
              </text>
            </g>
            {c && (
              <text className={`tx k ${c.errors ? 'warn' : ''}`} x={x.tool + 146} y={y + 16}>
                ×{c.calls}
                {c.errors ? ` · ${c.errors} err` : ''} · {c.p50_ms < 1000 ? `${Math.round(c.p50_ms)}ms` : `${(c.p50_ms / 1000).toFixed(1)}s`}
              </text>
            )}
            {back && <path className="ed dash" d={`M${x.tool + 140} ${ty} C ${x.tool + 230} ${ty}, ${x.back - 30} ${backY[back] + 22}, ${x.back} ${backY[back] + 22}`} style={{ opacity: 0.55 }} />}
          </g>
        );
      })}
      {backends.map((b) => (
        <Node key={b.id} id={b.id} x={x.back} y={backY[b.id]} w={135} h={44} label={b.label} sub={b.sub} extra={b.ext ? 'ext' : ''} title={`${b.label}: ${b.sub}`} />
      ))}
      <Node id="judge" x={x.sdk} y={H - 130} w={230} h={40} label="judge · validate.py" sub="pass / fail + reason" title="The query's own validate.py judges the returned answer" />
      <Node id="runs" x={x.sdk} y={H - 82} w={230} h={40} label="runs/<id>/" sub="results.jsonl · traces/" title="The run folder is the record" />
      <Node id="mlflow" x={x.mcp} y={H - 82} w={200} h={40} label="MLflow" sub="dataagentbench/evals" extra="ext" title="The central MLflow: one run, one trace per trial; linked, never read back" />
      <path className="ed" d={`M${x.tool} ${toolsTop + (tools.findIndex((t) => t.name === 'return_answer') + 0.5) * rowH} C ${x.tool - 60} ${H - 110}, ${x.sdk + 260} ${H - 110}, ${x.sdk + 230} ${H - 110}`} />
      <path className="ed" d={`M${x.sdk + 115} ${H - 90}V${H - 82}`} />
      <path className="ed dash" d={`M${x.sdk + 230} ${H - 62}H${x.mcp}`} />
      <text className="cap" x={10} y={H - 8}>
        {counts ? `this trace: ${Object.entries(counts).map(([n, c]) => `${n} ×${c.calls}`).join(' · ')}` : 'pick a trace to overlay call counts'} · click a node
      </text>
    </svg>
  );
}

/** A form built from a tool's JSON schema; posts to the playground and shows the result. */
export function ToolForm({ spec, agent, dataset, initial, original, onResult }: { spec: ToolSpec; agent: string; dataset: string; initial?: Record<string, unknown>; original?: { output: string; label: string } | null; onResult?: (r: PlayResult) => void }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<PlayResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const v: Record<string, string> = {};
    for (const [k, p] of Object.entries(spec.schema.properties)) {
      const x = initial?.[k];
      v[k] = x == null ? '' : p.type === 'array' ? (Array.isArray(x) ? x.join(', ') : String(x)) : String(x);
    }
    setValues(v);
    setRes(null);
    setErr(null);
  }, [spec, initial]);
  const disabled = spec.playground === 'off';
  const big = (k: string) => ['sql', 'code', 'instruction', 'answer'].includes(k);
  async function run() {
    setBusy(true);
    setErr(null);
    const input: Record<string, unknown> = {};
    for (const [k, p] of Object.entries(spec.schema.properties)) {
      const raw = values[k] ?? '';
      if (raw === '') continue;
      input[k] = p.type === 'integer' ? Number(raw) : p.type === 'array' ? raw.split(',').map((s) => s.trim()).filter(Boolean) : raw;
    }
    try {
      const r = await fetch(`/api/agent/tools/${spec.name}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ agent, dataset, input }) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail ?? `${r.status}`);
      setRes(j as PlayResult);
      onResult?.(j as PlayResult);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      className="toolform"
      onSubmit={(e) => {
        e.preventDefault();
        if (!disabled && !busy) void run();
      }}
    >
      {Object.entries(spec.schema.properties).length === 0 && <p className="small muted">This tool takes no input.</p>}
      {Object.entries(spec.schema.properties).map(([k, p]) => (
        <label key={k} className="field">
          <span className="label">
            {k}
            {spec.schema.required.includes(k) ? '' : ' · optional'}
            {p.type === 'array' ? ' · comma-separated' : ''}
            {p.description ? ` — ${p.description}` : ''}
          </span>
          {big(k) ? <textarea value={values[k] ?? ''} onChange={(e) => setValues({ ...values, [k]: e.target.value })} rows={k === 'code' ? 10 : 5} spellCheck={false} /> : <input type={p.type === 'integer' ? 'number' : 'text'} value={values[k] ?? ''} onChange={(e) => setValues({ ...values, [k]: e.target.value })} />}
        </label>
      ))}
      <div className="filters">
        <button type="submit" className="btn" disabled={disabled || busy}>
          {busy ? 'Running…' : spec.playground === 'echo' ? 'Run tool (echo)' : 'Run tool'}
        </button>
        <span className="count">
          {disabled ? 'off here: this tool calls a model (DAB_PLAYGROUND_LLM=1 to allow)' : spec.playground === 'echo' ? 'records nothing; in a trial this ends the run' : `against ${dataset} · same guards as a trial · not a trial`}
        </span>
      </div>
      {err && <div className="code err">{err}</div>}
      {res && !original && (
        <div className={`code ${res.error ? 'err' : ''}`}>
          <p className="label">
            {res.error ? 'error' : 'output'} · {fmtInt(res.chars)} chars{res.cut ? ' (cut at 10 000)' : ''} · {res.elapsed_s < 1 ? `${Math.round(res.elapsed_s * 1000)} ms` : `${res.elapsed_s.toFixed(1)} s`}
          </p>
          <pre>{res.output}</pre>
        </div>
      )}
      {res && original && <Compare original={original} fresh={res} />}
    </form>
  );
}

/** Original output beside the re-run, with the first differing line named. */
export function Compare({ original, fresh }: { original: { output: string; label: string }; fresh: PlayResult }) {
  const a = original.output.split('\n');
  const b = fresh.output.split('\n');
  let first = -1;
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if (a[i] !== b[i]) {
      first = i;
      break;
    }
  }
  return (
    <>
      <p className="small">
        {first < 0 ? <span className="v-ok">identical output</span> : <span className="v-warn">differs from line {first + 1}</span>} · original {fmtInt(original.output.length)} chars, re-run {fmtInt(fresh.chars)} chars in {fresh.elapsed_s < 1 ? `${Math.round(fresh.elapsed_s * 1000)} ms` : `${fresh.elapsed_s.toFixed(1)} s`}
      </p>
      <div className="compare">
        <div className="code">
          <p className="label">original · {original.label}</p>
          <pre>{original.output || '(empty)'}</pre>
        </div>
        <div className={`code ${fresh.error ? 'err' : 'band'}`}>
          <p className="label">re-run · now{fresh.error ? ' · error' : ''}</p>
          <pre>{fresh.output || '(empty)'}</pre>
        </div>
      </div>
    </>
  );
}

function mainInput(input: Record<string, unknown> | undefined): string {
  if (!input) return '';
  const v = input.sql ?? input.code ?? input.answer ?? input.table ?? input.path ?? input.term ?? input.instruction ?? '';
  return String(v);
}

/** Every span of a trial as a row; tool rows carry a re-run button. */
export function Replay({ spans, onlyTools, filterTool, onRerun }: { spans: Span[]; onlyTools: boolean; filterTool: string | null; onRerun: (s: Span, i: number) => void }) {
  const [open, setOpen] = useState<number | null>(null);
  let turn = 0;
  const rows = spans.map((s, i) => {
    if (s.kind === 'turn') turn += 1;
    return { s, i, turn };
  });
  const shown = rows.filter(({ s }) => (onlyTools ? s.kind === 'tool' : true) && (filterTool ? s.kind === 'tool' && s.name === filterTool : true));
  const billed = spans.filter((s) => s.tokens?.billed).map((s) => s.tokens as SpanTokens);
  const sum = (k: keyof SpanTokens) => billed.reduce((a, t) => a + (t[k] as number), 0);
  const hasTokens = spans.some((s) => s.tokens);
  return (
    <div className="tw">
      <table>
        <caption>
          {hasTokens
            ? `billed tokens: ${fmtInt(sum('total'))} over ${billed.length} API messages — ${fmtInt(sum('input') + sum('cache_creation'))} fresh input, ${fmtInt(sum('cache_read'))} cache read, ${fmtInt(sum('output'))} output. A message that emits several blocks is billed once, on its first row; a tool row shows the message that issued the call.`
            : 'no per-message usage in this trace (recorded from 22 Sep 2026 on; `dab runs backfill-usage <run>` fills older runs from the SDK session transcript when one exists)'}
        </caption>
        <thead>
          <tr>
            <th className="num">t</th>
            <th className="num">turn</th>
            <th>sent</th>
            <th>received</th>
            <th className="num">chars</th>
            <th className="num">elapsed</th>
            <th className="num">billed tokens</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {shown.map(({ s, i, turn }) => {
            const sent = s.kind === 'turn' ? s.text || (s.tool_calls?.length ? `(calls ${s.tool_calls.map((c) => c.replace('mcp__dab__', '')).join(', ')})` : '(thinking)') : `${s.name} · ${mainInput(s.input)}`;
            const recv = s.kind === 'turn' ? '' : s.output || '';
            const isOpen = open === i;
            return (
              <tr key={i} className={s.status === 'ERROR' ? 'warnrow' : s.kind === 'turn' ? 'dim' : ''}>
                <td className="num">{s.start.toFixed(1)}s</td>
                <td className="num">{turn}</td>
                <td className="mono small replay-cell">
                  <pre className="cell">{isOpen ? sent : sent.slice(0, 140) + (sent.length > 140 ? '…' : '')}</pre>
                  {(sent.length > 140 || recv.length > 140) && (
                    <button type="button" className="linkbtn small" onClick={() => setOpen(isOpen ? null : i)}>
                      {isOpen ? 'less' : 'more'}
                    </button>
                  )}
                </td>
                <td className="mono small replay-cell">
                  <pre className="cell">{isOpen ? recv : recv.slice(0, 140) + (recv.length > 140 ? '…' : '')}</pre>
                </td>
                <td className="num">{s.kind === 'tool' ? fmtInt((s.output ?? '').length) : fmtInt((s.text ?? '').length)}</td>
                <td className="num">{(s.end - s.start) < 1 ? `${Math.round((s.end - s.start) * 1000)}ms` : `${(s.end - s.start).toFixed(1)}s`}</td>
                <td className="num">
                  {s.tokens ? (
                    <span className={s.tokens.billed ? '' : 'muted'} title={`${s.tokens.input} input · ${s.tokens.cache_creation} cache write · ${s.tokens.cache_read} cache read · ${s.tokens.output} output${s.tokens.billed ? '' : ' — billed on an earlier row of the same message'}`}>
                      {s.tokens.billed ? fmtTok(s.tokens.total) : `(${fmtTok(s.tokens.total)})`}
                      <span className="path">{fmtTok(s.tokens.input + s.tokens.cache_creation)} in · {fmtTok(s.tokens.cache_read)} cached · {fmtTok(s.tokens.output)} out</span>
                    </span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td>
                  {s.kind === 'tool' && (
                    <span className="rowacts">
                      <button type="button" className="tog" onClick={() => onRerun(s, i)}>
                        re-run with changes
                      </button>
                      <button type="button" className="tog" onClick={() => void navigator.clipboard.writeText(mainInput(s.input))} title="copy the call's main input (sql / code / …) to the clipboard">
                        copy input
                      </button>
                    </span>
                  )}
                  {s.status === 'ERROR' && <span className="tag warn"> error</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function TraceLine({ runId, queryId, trial, passed, cost }: { runId: string; queryId: string; trial: number; passed: boolean | null; cost: number | null }) {
  return (
    <span>
      <Link to={questionPath(queryId)} className="mono">
        {queryId}
      </Link>{' '}
      trial {trial} · {passed == null ? 'not scored' : passed ? <span className="v-ok">pass</span> : <span className="v-warn">fail</span>} · {fmtUsd(cost, 3)} ·{' '}
      <Link to={trialPath(runId, trialId({ query_id: queryId, trial }))} className="mono">
        full trace
      </Link>
    </span>
  );
}
