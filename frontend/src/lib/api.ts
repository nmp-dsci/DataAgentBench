import { useEffect, useState } from 'react';

// ── shapes served by src/dab_bench/serving/app.py ─────────────────────────
export type Health = { status: string; version: string; code_sha: string; source: { repo: string; commit: string; ingested_at: string }; rescored: boolean };
export type Stats = {
  commit: string;
  datasets_total_upstream: number;
  queries_total_upstream: number;
  datasets: number;
  queries: number;
  deferred_datasets: string[];
  deferred_queries: number;
  with_gold: number;
  with_validator: number;
  validator_styles: Record<string, number>;
  engines: Record<string, number>;
  bytes_in_scope: number;
  bytes_total: number;
  answer_files: number;
  answer_rows: number;
  answer_rows_unmatched: number;
  leaderboard_entries: number;
  rescored: boolean;
  trials_judged?: number;
  never_passed?: string[];
  under_10pct?: string[];
};
export type Trials = { n: number; passed: number; rate: number | null };
export type DatasetSummary = {
  key: string;
  folder: string;
  n_queries: number;
  queries: string[];
  engines: string[];
  n_dbs: number;
  bytes_total: number;
  description_bytes: number;
  hints_bytes: number;
  trials: Trials | null;
};
export type Db = { name: string; engine: string; config: Record<string, unknown>; file?: string; in_manifest?: boolean; bytes?: number | null; sha256?: string | null };
export type DatasetDetail = DatasetSummary & { released: boolean; dbs: Db[]; description: string; hints: string; query_rows: QuerySummary[] };
export type QueryTrialsSummary = { n: number; passed: number; rate: number | null; timed_out: number; best_file: string | null; best_rate: number | null };
export type QuerySummary = {
  id: string;
  dataset_key: string;
  query_id: number;
  question: string;
  gold_lines: number;
  gold_preview: string;
  gold_text: string;
  validator_style: string;
  validator_lines: number;
  footnote: string | null;
  site_text_matches: boolean | null;
  trials: QueryTrialsSummary | null;
};
export type TrialFile = {
  name: string;
  label: string;
  rank: number | null;
  n: number;
  passed?: number;
  timed_out?: number;
  passes?: { run: number; answer: string }[];
  fails?: { run: number; answer: string; reason: string }[];
};
export type QueryTrials = { rescored: boolean; n: number; passed?: number; timed_out?: number; files: TrialFile[] };
export type QueryDetail = {
  id: string;
  dataset_key: string;
  query_id: number;
  question: string;
  gold_text: string;
  gold_lines: number;
  validator: { style: string; lines: number; reads_gold_file: boolean; source: string };
  released: boolean;
  on_site: boolean;
  site_text_matches: boolean | null;
  footnote: string | null;
  dataset: DatasetSummary;
  hints: string;
  trials: QueryTrials | null;
};
export type ValidatorStyle = { style: string; n: number; ids: string[]; longest: number; trials: { n: number; passed: number } | null };
export type Validators = { styles: ValidatorStyle[]; reads_gold_file: string[]; total_lines: number };
export type LeaderboardRow = { rank: number; agent: string; trials: number; passAt1: number; promptGroup: string; team: string; teamUrl?: string; prUrl?: string; date: string; note?: string };
export type Stratified = { columns: { key: string; label: string }[]; rows: Record<string, string | number>[]; overall: Record<string, string | number> };
export type AnswerFile = {
  name: string;
  upstream_path: string;
  label: string;
  agent: string | null;
  rank: number | null;
  pass_at_1_site: number | null;
  stratified: string | null;
  rows: number;
  rows_unmatched: number;
  queries: number;
  runs_per_query: number[];
};
export type Leaderboard = { updatedAt: string; sources: string[]; overallLeaderboard: LeaderboardRow[]; promptqlStratified: Stratified; baselineStratified: Stratified; answer_files: AnswerFile[] };
export type PerFile = { rows: number; passed: number; micro: number | null; macro: number | null; per_dataset: Record<string, number> };
export type SiteCheckFile = { table: string; column: string; per_dataset: Record<string, { ours: number; site: number; diff: number }>; overall_site: number | null; overall_ours_macro: number | null };
export type TrialsIndex = {
  summary: { generated_at: string; commit: string; seconds: number; timeout_s: number; rows: number; queries: number; files: number; timed_out: number; never_passed: string[]; under_10pct: string[]; at_least_95pct: string[]; site_check_max_abs_diff: number };
  per_file: Record<string, PerFile>;
  site_check: { files: Record<string, SiteCheckFile>; max_abs_diff: number };
};

// ── fetching ───────────────────────────────────────────────────────────────
export async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return (await r.json()) as T;
}

export function useGet<T>(url: string | null): { data: T | null; error: string | null; loading: boolean } {
  const [state, set] = useState<{ data: T | null; error: string | null; loading: boolean }>({ data: null, error: null, loading: !!url });
  useEffect(() => {
    if (!url) return;
    let alive = true;
    set({ data: null, error: null, loading: true });
    get<T>(url)
      .then((d) => alive && set({ data: d, error: null, loading: false }))
      .catch((e: Error) => alive && set({ data: null, error: e.message, loading: false }));
    return () => {
      alive = false;
    };
  }, [url]);
  return state;
}

// ── formatting ─────────────────────────────────────────────────────────────
export function fmtPct(x: number | null | undefined, digits = 0): string {
  return x == null ? '—' : `${(x * 100).toFixed(digits)}%`;
}
export function fmtBytes(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)} GB`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)} KB`;
  return `${n} B`;
}
export function fmtInt(n: number | null | undefined): string {
  return n == null ? '—' : n.toLocaleString('en-GB');
}
export function shortSha(sha: string | undefined): string {
  return sha ? sha.slice(0, 7) : '…';
}
export function queryPath(id: string): string {
  const [ds, n] = id.split('/');
  return `/queries/${ds}/${n}`;
}
export const STYLE_LABEL: Record<string, string> = {
  regex: 'regex / number',
  'reads-gold-file': 'reads ground_truth.csv',
  substring: 'substring / list',
  levenshtein: 'levenshtein',
};

// ── our runs (runs/<id>/ on disk, served by /api/runs) ────────────────────────
export type DatasetRate = { passed: number; n: number; rate: number | null; queries: number };
export type RunSummary = {
  run_id: string;
  agent: string;
  fingerprint: string;
  context_sha: string;
  model: string;
  effort: string;
  split: string;
  n_queries: number;
  trials: number;
  hints: boolean;
  dry_run: boolean;
  started_at: string;
  finished_at: string | null;
  note: string;
  kind: string;
  challenger_of: string | null;
  mlflow_run_id: string | null;
  mlflow_url: string | null;
  passed: number | null;
  scored: number | null;
  n: number | null;
  pass_rate_macro: number | null;
  pass_rate_micro: number | null;
  cost_usd: number | null;
  duration_ms: number | null;
  errors: number | null;
  timeouts: number | null;
  per_dataset: Record<string, DatasetRate> | null;
  role: RunRole;
  profile: Profile;
};
/** GET /api/runs/compare: two runs on the same queries, grouped by dataset, validator style or query. */
export type CompareGroup = 'dataset' | 'style' | 'query';
export type CompareRate = { passed: number; n: number; rate: number; queries: number };
export type CompareSide = {
  run: RunSummary | null;
  queries: number;
  passed: number;
  scored: number;
  pass_rate_micro: number | null;
  pass_rate_macro: number | null;
  timeouts: number;
  errors: number;
  rate_limited: number;
  cost_usd: number;
  profile: Profile;
};
export type CompareResp = {
  focus: string;
  challenger: string | null;
  group: CompareGroup;
  scope: 'common' | 'all';
  common_queries: number;
  scored_queries: Record<string, number>;
  sides: Record<string, CompareSide>;
  groups: ({ key: string } & Record<string, CompareRate | string>)[];
  fixed: string[];
  broken: string[];
};
export type RunRole = 'champion' | 'challenger' | 'superseded' | 'smoke' | 'dry';
export type Board = { champion: string; champion_run_id: string | null; runs: RunSummary[] };
export type Stat = { mean: number; p50: number; p95: number; max: number; sum: number };
export type ProfileKey = 'turns' | 'tool_calls' | 'wall_s' | 'fresh_in' | 'cache_read' | 'output' | 'total' | 'cost_usd';
export type Profile = {
  n: number;
  metrics: Record<ProfileKey, Stat>;
  cache_hit_rate: number | null;
  cost_per_pass: number | null;
  cost_per_trial: number | null;
  tokens_per_pass: number | null;
  timeout_rate: number | null;
  error_rate: number | null;
  fail_rate: number | null;
  exhausted: number;
};
export type TrialRow = {
  query_id: string;
  dataset: string;
  trial: number;
  question: string;
  answer: string;
  passed: boolean | null;
  reason: string;
  n_turns: number;
  duration_ms: number;
  cost_usd: number | null;
  input_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  output_tokens: number;
  tool_calls: number;
  error: string | null;
  terminal_reason: string | null;
  timed_out: boolean;
  rate_limited?: boolean;
  trace_file: string | null;
  mlflow_trace_id: string | null;
  mlflow_trace_url: string | null;
  gold: GoldRef | null;
};
export type GoldRef = { preview: string; lines: number; text: string };
export type RunDetail = RunSummary & { max_turns: number; workers: number; code_sha: string; upstream_commit: string; query_ids: string[]; results: TrialRow[]; versus: RunSummary | null };
/** One span of the tree tracking/tracing.py logs to MLflow, rebuilt server-side from the same stream. */
export type SpanTokens = { input: number; cache_read: number; cache_creation: number; output: number; total: number; billed: boolean; message_id: string };
export type Span = { kind: 'turn' | 'tool'; name: string; start: number; end: number; status: 'OK' | 'ERROR'; text?: string; thinking_chars?: number; tool_calls?: string[]; input?: Record<string, unknown>; output?: string; tokens: SpanTokens | null };
export type TraceBlock = { type: string; text?: string; thinking?: string; name?: string; input?: Record<string, unknown>; content?: string; is_error?: boolean; tool_use_id?: string; id?: string };
export type TraceEntry = { role: 'system' | 'user' | 'assistant' | 'tool'; content: string | TraceBlock[]; t?: number };
export type ToolCall = { tool: string; input: Record<string, unknown>; output: string; chars: number; elapsed_s: number; error: boolean };
export type Trace = {
  query_id: string;
  dataset: string;
  trial: number;
  answer: string;
  final_text: string;
  trace: TraceEntry[];
  tool_calls: ToolCall[];
  n_turns: number;
  duration_ms: number;
  cost_usd: number | null;
  input_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  output_tokens: number;
  error: string | null;
  model: string;
  effort: string;
  context_sha: string;
  system_prompt_chars: number;
  passed: boolean | null;
  reason: string;
  mlflow_trace_id: string | null;
  mlflow_trace_url: string | null;
  mlflow_embeddable: boolean;
  gold: GoldRef | null;
  spans: Span[];
};
export type ContextPack = { dataset: string; files: Record<string, string>; curation: { model: string; cost_usd: number | null; input_tokens: number; output_tokens: number; duration_ms: number } | null };

export function fmtUsd(x: number | null | undefined, digits = 2): string {
  return x == null ? '—' : `$${x.toFixed(digits)}`;
}
export function fmtDur(ms: number | null | undefined): string {
  if (ms == null) return '—';
  const s = Math.round(ms / 1000);
  if (s < 90) return `${s}s`;
  const m = Math.round(s / 60);
  return m < 90 ? `${m} min` : `${(m / 60).toFixed(1)} h`;
}
/** Tokens read like the SDK prints them: 12.5k, 1.2M. */
export function fmtTok(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e4) return `${(n / 1e3).toFixed(0)}k`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return String(Math.round(n));
}
export function fmtSec(s: number | null | undefined): string {
  return s == null ? '—' : fmtDur(s * 1000);
}
export const ROLE_LABEL: Record<RunRole, string> = {
  champion: 'champion',
  challenger: 'challenger',
  superseded: 'superseded',
  smoke: 'smoke',
  dry: 'dry run',
};
export function traceKey(r: { dataset: string; query_id: string; trial: number }): string {
  return `${r.dataset}_${r.query_id.split('/')[1]}_t${r.trial}`;
}
