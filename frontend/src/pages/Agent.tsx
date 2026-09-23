import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { type AgentDetail, AgentGraph, type AgentsBoard, type NodeId, type PlayResult, type PromptResp, Replay, ToolForm, TraceLine, toolCounts } from '../lib/agent';
import { type Board, type RunDetail, type Span, type Trace, fmtInt, useGet } from '../lib/api';
import { Gold, Loading } from '../lib/ui';
import { agentPath, apiTrialPath, datasetPath, questionPath, runPath, trialId, useLens } from '../lib/url';

/** sessionStorage key: the last Agent view in this browser tab, as `/agent/<v>?…`. The nav's bare
 *  `/agent` redirects there (routes.tsx). */
export const AGENT_VIEW = 'dab.agent.view';

/** One page: the agent system as a graph, a node panel with the tool playground, and a trial replayed turn by turn.
 *  The version is the subject, so it is the path (`/agent/champion`); the run, the trial (its id,
 *  `deps_dev_v1/1/t1`), the node and the dataset are the lens. */
export function Agent() {
  const { version: agent = 'champion' } = useParams();
  const [sp, set] = useLens();
  const nav = useNavigate();
  const { pathname, search: qs } = useLocation();
  const runId = sp.get('run') ?? '';
  const key = sp.get('trial') ?? '';
  const node = (sp.get('node') as NodeId | null) ?? null;

  // remember this view, so leaving the tab and coming back through the nav restores it
  useEffect(() => {
    try {
      sessionStorage.setItem(AGENT_VIEW, `${pathname}${qs}`);
    } catch {
      /* storage unavailable: the URL alone still works */
    }
  }, [pathname, qs]);

  const { data: board } = useGet<AgentsBoard>('/api/agents');
  const { data: detail, error } = useGet<AgentDetail>(`/api/agents/${agent}`);
  const { data: runs } = useGet<Board>('/api/runs');
  const { data: run } = useGet<RunDetail>(runId ? `/api/runs/${runId}` : null);
  const { data: trace } = useGet<Trace>(runId && key ? apiTrialPath(runId, key) : null);
  const dataset = sp.get('dataset') ?? trace?.dataset ?? detail?.datasets[0] ?? '';
  const { data: prompt } = useGet<PromptResp>(detail && dataset && node === 'prompt' ? `/api/agents/${detail.name}/prompt?dataset=${dataset}` : null);

  const [onlyTools, setOnlyTools] = useState(true);
  const [rerun, setRerun] = useState<{ tool: string; input: Record<string, unknown>; original: { output: string; label: string } } | null>(null);
  const [lastResult, setLastResult] = useState<PlayResult | null>(null);
  useEffect(() => setRerun(null), [key]);
  const selectNode = (n: NodeId) => {
    setRerun(null);
    set({ node: n });
  };

  const counts = useMemo(() => (trace ? toolCounts(trace.spans) : null), [trace]);
  if (!detail) return <Loading error={error} />;
  const tool = node?.startsWith('tool:') ? detail.tools.find((t) => t.name === node.slice(5)) ?? null : null;
  const champRun = runs?.runs.find((r) => r.run_id === runs.champion_run_id) ?? null;
  const trials = run?.results.filter((r) => r.trace_file) ?? [];
  const question = trace ? (trace.trace.find((e) => e.role === 'user')?.content as string | undefined) ?? null : null;

  function onRerun(s: Span, i: number) {
    setRerun({ tool: s.name, input: s.input ?? {}, original: { output: s.output ?? '', label: `span ${i + 1}, ${s.start.toFixed(1)}s` } });
    set({ node: `tool:${s.name}` });
  }

  return (
    <>
      <p className="label">
        agent · {detail.name}@{detail.fingerprint} · {detail.champion ? 'champion' : 'challenger'} · {detail.tools.length} tools · {String(detail.config.model)} @ {String(detail.config.effort ?? 'medium')} · max {String(detail.config.max_turns)} turns
      </p>
      <h1>
        {detail.name} is one agent, one system prompt and {detail.tools.length} tools: the pack is what it knows, <em>{detail.tools.some((t) => t.name === 'query_db') ? 'query_db' : detail.tools[0]?.name}</em> is what it does
      </h1>
      <p className="lead">
        The graph is generated from <code>agents/{detail.name}/agent.yaml</code> and the tool server's own schemas. Click a node for its config, source and — for a tool — a form that runs it with the trial's guards (read-only role, network-off sandbox; never a model). Pick a trace to
        overlay call counts and replay it turn by turn.
      </p>

      <div className="filters">
        <label className="pick">
          <span className="label">agent</span>
          <select value={agent} onChange={(e) => nav(agentPath(e.target.value, Object.fromEntries([...sp.entries()].filter(([k]) => k !== 'node'))), { replace: true })}>
            <option value="champion">champion → {board?.champion ?? '…'}</option>
            {board?.versions.map((v) => (
              <option key={v.name} value={v.name}>
                {v.name} @ {v.fingerprint.slice(0, 7)}
              </option>
            ))}
          </select>
        </label>
        <label className="pick">
          <span className="label">dataset</span>
          <select value={dataset} onChange={(e) => set({ dataset: e.target.value })}>
            {detail.datasets.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        <label className="pick">
          <span className="label">run</span>
          <select value={runId} onChange={(e) => set({ run: e.target.value, trial: null })}>
            <option value="">— none —</option>
            {runs?.runs
              .filter((r) => !r.dry_run)
              .map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.run_id === champRun?.run_id ? '★ ' : ''}
                  {r.run_id} · {r.role}
                </option>
              ))}
          </select>
        </label>
        {run && (
          <label className="pick">
            <span className="label">trial</span>
            <select value={key} onChange={(e) => set({ trial: e.target.value, dataset: null })}>
              <option value="">— pick —</option>
              {trials.map((r) => (
                <option key={trialId(r)} value={trialId(r)}>
                  {r.query_id} t{r.trial} · {r.passed == null ? 'not scored' : r.passed ? 'pass' : 'fail'} · {r.n_turns} turns
                </option>
              ))}
            </select>
          </label>
        )}
        {trace && (
          <span className="count">
            <TraceLine runId={runId} queryId={trace.query_id} trial={trace.trial} passed={trace.passed} cost={trace.cost_usd} />
            {trace.gold && (
              <>
                {' · gold '}
                <Gold preview={trace.gold.preview} lines={trace.gold.lines} full={trace.gold.text} />
              </>
            )}
          </span>
        )}
      </div>

      <div className="agent-cols">
        <div className="tw graph-wrap">
          <AgentGraph detail={detail} counts={counts} selected={node} onSelect={selectNode} question={question} />
        </div>
        <div className="card nodepanel">
          {!node && (
            <>
              <h3>Nothing selected</h3>
              <p className="small">Click a node. Tools open a form; the others show their configuration and where it comes from.</p>
              <dl className="kv">
                <dt>model</dt>
                <dd>{String(detail.config.model)} at effort {String(detail.config.effort ?? 'medium')}</dd>
                <dt>budgets</dt>
                <dd>
                  max {String(detail.config.max_turns)} turns · {String(detail.config.timeout_s)} s per trial · {String(detail.config.exec_timeout_s)} s per execute_python
                </dd>
                <dt>hints</dt>
                <dd>{detail.config.hints ? 'on' : 'off'} (the benchmark's --use_hints)</dd>
                <dt>fingerprint</dt>
                <dd className="mono">{detail.fingerprint} = sha256(system.md + agent.yaml + helper.py)</dd>
              </dl>
            </>
          )}
          {node === 'question' && (
            <>
              <h3>The question is the whole user message</h3>
              <p className="small">Everything the agent knows about the dataset is in the system prompt (decision D7-A); the user turn is the benchmark question verbatim.</p>
              <div className="code">
                <pre>{question ?? '(pick a trace to see its question)'}</pre>
              </div>
              {trace?.gold && (
                <div className="code band">
                  <p className="label">gold · {trace.gold.lines} line{trace.gold.lines === 1 ? '' : 's'}</p>
                  <pre>{trace.gold.text}</pre>
                </div>
              )}
              {trace && (
                <p className="small">
                  <Link to={questionPath(trace.query_id)}>gold, validator and the leaderboard's trials for {trace.query_id}</Link>
                </p>
              )}
            </>
          )}
          {node === 'sdk' && (
            <>
              <h3>Agent SDK · a claude child on the subscription</h3>
              <p className="small">
                <code>agent/session.py</code> builds <code>ClaudeAgentOptions</code>: no built-in tools, the <code>dab</code> MCP server only, <code>bypassPermissions</code>, <code>setting_sources=[]</code>, the model and effort from <code>agent.yaml</code>. Billing is the subscription; <code>require_live()</code> refuses to
                start with a per-token key present.
              </p>
              <div className="code band">
                <p className="label">agents/{detail.name}/agent.yaml</p>
                <pre>{detail.files['agent.yaml'] ?? JSON.stringify(detail.config, null, 2)}</pre>
              </div>
            </>
          )}
          {node === 'prompt' && (
            <>
              <h3>System prompt for {dataset}</h3>
              <p className="small">
                <code>system.md</code> (behaviour, {fmtInt(detail.files['system.md']?.length)} chars) + the pack's <code>summary.md</code>, <code>pitfalls.md</code> and the upstream description.{' '}
                {prompt && (
                  <>
                    Composed: {fmtInt(prompt.chars)} chars, context <code>{prompt.context_sha}</code>.
                  </>
                )}
              </p>
              <div className="code band">
                <p className="label">composed · {dataset}</p>
                <pre>{prompt?.prompt ?? 'loading…'}</pre>
              </div>
            </>
          )}
          {node === 'mcp' && (
            <>
              <h3>mcp "dab" · one in-process server per trial</h3>
              <p className="small">
                <code>make_tool_server</code> in <code>agent/tools.py</code> wraps every spec around <code>call_tool</code>; <code>strict_mcp_config</code> means no other server can appear. The playground calls the same <code>call_tool</code>, so a tool cannot behave differently here.
              </p>
              <ul className="tight">
                {detail.tools.map((t) => (
                  <li key={t.name}>
                    <button type="button" className="linkbtn mono" onClick={() => selectNode(`tool:${t.name}`)}>
                      {t.name}
                    </button>{' '}
                    <span className="muted small">· {t.backend}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
          {node === 'postgres' && (
            <>
              <h3>Postgres · role dab_agent</h3>
              <p className="small">
                All 12 datasets in one schema <code>dataagentbench</code>, tables <code>&lt;dataset&gt;_&lt;table&gt;</code>. The agent's role is read-only (<code>default_transaction_read_only</code>), <code>statement_timeout</code> 60 s, search_path set. Database <code>dab</code> on the central nmp-central-ai Postgres (:5432) since 22 Sep 2026 (platform D13).
              </p>
              <p className="small">
                <Link to={datasetPath(dataset)}>{dataset}'s stores and tables</Link> · <code>list_db</code> shows what the agent sees.
              </p>
            </>
          )}
          {node === 'sandbox' && (
            <>
              <h3>Sandbox · {detail.sandbox_built ? 'dab-sandbox:py312, built' : 'image not built'}</h3>
              <p className="small">
                One container per run, <code>--network none</code>, a fresh Python process per call, cwd <code>/work/&lt;trial&gt;</code> where <code>query_db(save_as=…)</code> parquet lands. No database credential inside the box (decision D3-A).{' '}
                {!detail.sandbox_built && (
                  <>
                    Build it with <code>make sandbox</code>.
                  </>
                )}
              </p>
            </>
          )}
          {node === 'model' && (
            <>
              <h3>Haiku 4.5 · llm_extract only</h3>
              <p className="small">
                The one tool that calls a model: batches of 40 rows, ≤ 2 000 rows, writes the rows plus a <code>label</code> column to parquet. It bills the subscription, so the playground keeps it off (decision D8-A){detail.playground_llm ? ' — overridden by DAB_PLAYGROUND_LLM=1 on this server' : ''}.
              </p>
            </>
          )}
          {node === 'pack' && (
            <>
              <h3>The context pack · data/context/{dataset}/</h3>
              <p className="small">
                Generated by code (<code>dab context build</code>: tables, schema, profile, samples, joins) and curated once by a Sonnet session that never sees a question (<code>summary.md</code>, <code>pitfalls.md</code>). <code>read_context</code> and <code>search_context</code> read it; the summary and pitfalls are also in the system prompt.
              </p>
              <p className="small">
                <a href={`/api/context/${dataset}`}>the pack as JSON</a>
              </p>
            </>
          )}
          {node === 'judge' && (
            <>
              <h3>Judge · the query's own validate.py</h3>
              <p className="small">The returned answer is judged by the same validator the leaderboard rows were rescored with (<code>eval/validators.py</code>), in a worker process. Pass or fail with a reason; a rate-limited trial is neither.</p>
              {trace && (
                <div className={`answer ${trace.passed == null ? '' : trace.passed ? 'ok' : 'no'}`}>
                  <p className="label">this trial · {trace.passed == null ? 'not scored' : trace.passed ? 'pass' : 'fail'}</p>
                  <pre className="wrap-any">{trace.answer || '(no answer)'}</pre>
                  {trace.reason && <p className="reason">{trace.reason}</p>}
                </div>
              )}
            </>
          )}
          {node === 'runs' && (
            <>
              <h3>The run folder is the record</h3>
              <p className="small">
                <code>runs/&lt;id&gt;/</code>: run.json, results.jsonl (one row per query × trial), traces/, the agent's files and the composed per-dataset prompts. The <Link to="/runs">Runs board</Link> reads only these.
              </p>
              {runId && (
                <p className="small">
                  <Link to={runPath(runId)} className="mono">
                    {runId}
                  </Link>
                </p>
              )}
            </>
          )}
          {node === 'mlflow' && (
            <>
              <h3>MLflow · central, linked, never read back</h3>
              <p className="small">
                Experiment <code>dataagentbench/evals</code> on the nmp-central-ai server: one run per run folder (metrics per query, per trial), one trace per trial (the same span tree as the waterfall). {trace?.mlflow_trace_url && <a href={trace.mlflow_trace_url}>This trial's trace in MLflow</a>}
              </p>
            </>
          )}
          {tool && (
            <>
              <h3>
                {tool.name} · {tool.backend}
                {rerun && rerun.tool === tool.name ? ' · re-run' : ''}
              </h3>
              <p className="small">{tool.description}</p>
              {counts?.[tool.name] && (
                <p className="small">
                  In this trace: {counts[tool.name].calls} call{counts[tool.name].calls === 1 ? '' : 's'}, {counts[tool.name].errors} error{counts[tool.name].errors === 1 ? '' : 's'}, p50 {Math.round(counts[tool.name].p50_ms)} ms.{' '}
                  <button type="button" className="linkbtn" onClick={() => setOnlyTools(true)}>
                    show its rows below
                  </button>
                </p>
              )}
              <ToolForm spec={tool} agent={detail.name} dataset={dataset} initial={rerun?.tool === tool.name ? rerun.input : undefined} original={rerun?.tool === tool.name ? rerun.original : null} onResult={setLastResult} />
            </>
          )}
        </div>
      </div>

      <h2>
        {trace ? (
          <>
            Replay — {trace.query_id} trial {trace.trial}: {trace.spans.filter((s) => s.kind === 'tool').length} tool calls in {trace.n_turns || trace.spans.filter((s) => s.kind === 'turn').length} turns, {trace.spans.filter((s) => s.status === 'ERROR').length} errored
          </>
        ) : (
          'Replay — pick a run and a trial above to see every turn'
        )}
      </h2>
      {trace ? (
        <>
          <div className="filters">
            <button type="button" className={`tog ${onlyTools ? 'on' : ''}`} onClick={() => setOnlyTools(true)}>
              tool rows only
            </button>
            <button type="button" className={`tog ${!onlyTools ? 'on' : ''}`} onClick={() => setOnlyTools(false)}>
              every span
            </button>
            {tool && counts?.[tool.name] && <span className="count">filtered to {tool.name} · click another node to clear</span>}
            {lastResult && <span className="count">last playground run: {lastResult.tool} · {lastResult.error ? 'error' : 'ok'}</span>}
          </div>
          <Replay spans={trace.spans} onlyTools={onlyTools} filterTool={tool && counts?.[tool.name] ? tool.name : null} onRerun={onRerun} />
        </>
      ) : (
        <p className="empty">A replay is the trace's span tree as rows: what each turn sent, what each tool returned, and a re-run button that opens the tool pre-filled so you can change the SQL or the code and compare.</p>
      )}
    </>
  );
}
