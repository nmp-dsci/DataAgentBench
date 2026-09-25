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
  pooled: boolean; // false: a reference file, kept out of each query's pooled rate
  pr: number | null; // read from this submission PR's branch, pinned at `commit`
  pr_url: string | null;
  commit: string | null;
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

// ── golden SQL ─────────────────────────────────────────────────────────────
export type GoldenRow = {
  id: number;
  query_id: string;
  sql: string;
  answer_text: string;
  passed: boolean | null;
  reason: string;
  row_count: number | null;
  duration_ms: number | null;
  error: string | null;
  note: string;
  author: string;
  upstream_commit: string;
  created_at: string;
  gold_match: GoldMatch | '';
  source: string; // where the SQL started: '' by hand, else a run's trial and call
  kind: GoldenKind;
  expected_answer: string; // evidence only
};
/** answer: judged by the validator. evidence: a judgment question; the rows are the evidence (D23). */
export type GoldenKind = 'answer' | 'evidence';
export type ProposalBrief = { id: number; kind: GoldenKind; passed: boolean | null; gold_match: GoldMatch | ''; duration_ms: number | null; created_at: string };
export type Proposal = ProposalBrief & { query_id: string; sql: string; expected_answer: string; answer_text: string; reason: string; row_count: number | null; error: string | null; replaces: string; note: string; author: string };
/** One line of the gold-vs-result diff: `del` gold only, `add` result only; `changed` = differing cell indexes of a paired line. */
export type GoldDiffLine = { op: 'eq' | 'del' | 'add'; gold: number | null; result: number | null; text: string; changed?: number[] };
export type GoldMatch = 'exact' | 'exact_values' | 'reordered' | 'differs';
export type GoldenBrief = { passed: boolean | null; gold_match: GoldMatch | ''; created_at: string; versions: number; author: string; note: string; kind: GoldenKind; source: string; origin: string /* where the SQL first came from, through re-saves */ };
export type GoldenList = { queries: (QuerySummary & { golden: GoldenBrief | null; proposal: ProposalBrief | null })[]; n: number; written: number; evidence: number; proposed: number; passing: number; exact: number };
export type GoldenOne = { query: QuerySummary; hints: string; current: GoldenRow | null; history: GoldenRow[]; proposal: Proposal | null; ledger?: Lines | null };
export type GoldenAttempt = {
  execution: { columns: string[]; rows: unknown[][]; row_count: number; truncated: boolean; duration_ms: number; error: string | null };
  answer_text: string;
  verdict: { passed: boolean | null; reason: string; timed_out?: boolean };
  gold_match: { match: GoldMatch | ''; detail: string };
  gold_diff: GoldDiffLine[]; // empty when the result recreates the gold (or is evidence, or errored)
  kind: GoldenKind;
  saved?: { id: number; created_at: string };
};

export async function post<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  const j = await r.json();
  if (!r.ok) throw new Error(j.detail ?? `${r.status} ${url}`);
  return j as T;
}

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
  scorecard: ScorecardTotals | null;
};
/** The scorecard (s06): each question scored three ways, with a category per failure. */
export type Rate = { passed: number; n: number };
export type ScoreTotals = { answer: Rate; sql: Rate; decision: Rate };
export type ScorecardTotals = {
  totals: ScoreTotals;
  by_split: Record<string, ScoreTotals> | null;
  goldens: number;
  optimise_first: { category: string; n: number; queries: string[] }[];
  submits_sql: boolean;
};
export type ScoreRow = {
  query_id: string;
  trial: number;
  answer: boolean | null;
  sql: boolean | null;
  decision: boolean | null;
  mode: string | null;
  step: string | null;
  golden_id: number | null;
  golden_kind: GoldenKind | null;
  category: string;
  detail: string;
  sql_detail?: string;
  decision_detail?: string;
  structure: Record<string, { golden: unknown; agent: unknown } | string>;
  result_diff?: GoldDiffLine[];
  split?: string | null;
  /** s08: the step the statement first breaks at, by the reader's ledger */
  breaks_at?: Component | null;
  ledger?: RowLedger;
};
/** The seven steps of a statement (eval/ledger.py COMPONENTS), in the order it is built. */
export type Component = 'sources' | 'keys' | 'parse' | 'filter' | 'metric' | 'rank' | 'shape';
export const COMPONENTS: Component[] = ['sources', 'keys', 'parse', 'filter', 'metric', 'rank', 'shape'];
export type Verdict = 'same' | 'differs' | 'none';
export type Lines = Record<Component, string>;
/** A scorecard row's ledger: the golden's lines, and where the agent's statement failed, its own. */
export type RowLedger = { golden: Lines; agent?: Lines; verdicts?: Record<Component, Verdict>; breaks_at?: Component | null; why?: string };
export type GoldenBriefSql = { id: number; kind: GoldenKind; sql: string; passed: boolean | null; gold_match: string; created_at: string };
export type AgentSubmission = { sql: string; mode: string; step: string; model_answer: string; columns: string[]; row_count: number; truncated: boolean; result: string; plan?: Lines | null };
/** GET /api/runs/compare: two runs on the same queries, grouped by dataset, validator style or query. */
export type CompareGroup = 'dataset' | 'style' | 'query';
export type CompareRate = { passed: number; n: number; rate: number; queries: number };
/** A rescored leaderboard answer file as a compare target: id is `lb:<name>`. */
export type Submission = {
  id: string;
  name: string;
  label: string;
  rank: number | null;
  pass_at_1_site: number | null;
  pass_rate_macro: number | null;
  passed: number;
  rows: number;
  trials: number;
  pooled: boolean;
  pr_url: string | null;
};
export type CompareSide = {
  run: RunSummary | null;
  submission: Submission | null;
  queries: number;
  passed: number;
  scored: number;
  pass_rate_micro: number | null;
  pass_rate_macro: number | null;
  timeouts: number;
  errors: number;
  rate_limited: number;
  cost_usd: number | null; // null for a submission: the rescore keeps pass / fail only
  profile: Profile | null;
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
export type PromotionCandidate = { version: string; run_id: string | null; passed: number | null; scored: number | null; n: number | null; heldout: ScoreTotals | null; scorecard: ScoreTotals | null; why_not: string };
/** `dab promote`'s latest verdict (agents/promotions.jsonl): D36, the most SQL passed wins, answers break a tie (D30 before 2026-09-25). */
export type Promotion = { at: string; rule: string; incumbent: string; winner: string; changed: boolean; reason: string; candidates: PromotionCandidate[]; champion_run_id: string | null; prompt_version?: number };
/** The champion over time (`eval/rounds.champion_history`): the reigns and every full-split run. */
export type Reign = { version: string; run_id: string; from: string; until: string | null; passed: number; scored: number; reason: string; lift: number | null };
export type HistoryPoint = { run_id: string; agent: string; started_at: string; passed: number; scored: number };
export type ChampionHistory = { reigns: Reign[]; points: HistoryPoint[]; promotions: Promotion[] };
export type Board = { champion: string; champion_run_id: string | null; runs: RunSummary[]; submissions: Submission[]; promotion: Promotion | null; history: ChampionHistory };

// ── optimisation rounds (/api/optimise): diagnostic → proposal → outcome ─────────
export type TallyCore = { n: number; before: number; after: number; improved: number; regressed: number; held: number; 'still failing': number; 'not scored': number };
/** A round's before → after over some questions: answers of all, and `sql` over those with a golden. */
export type Tally = TallyCore & { sql?: TallyCore };
/** `pass_at_1`: the leaderboard's number, the mean over datasets of each one's pass rate (s11). */
export type CardTotals = { totals: ScoreTotals; by_split: Record<string, ScoreTotals> | null; pass_at_1?: number | null };
export type RoundSummary = {
  version: string;
  parent: string | null;
  source_run: string;
  outcome_run: string | null;
  started_at: string;
  optimiser: { model: string; effort: string } | null;
  cost_usd: number | null;
  sessions: number;
  notes_written: number;
  sections_written?: number;
  method?: string;
  plan_first?: boolean;
  stages?: Stages;
  refusals: number;
  system_md_changed: boolean;
  split: { train: number; heldout: number } | null;
  /** s11 (D38): `all` when the round read every error of the 54, so nothing was held out. */
  trained_on?: 'train' | 'all' | 'crossfit';
  guards?: { literal: boolean; g1_review: boolean; g2_audit: boolean; g3_breadth: boolean; g4_routing: boolean } | null;
  before: CardTotals | null;
  after: CardTotals | null;
  changes: Tally;
  promoted_at: string | null;
};
export type VersionNode = { version: string; parent: string | null; measured_against: string | null; run_id: string | null; passed: number | null; scored: number | null; fingerprint: string; started_at: string | null; model?: string; sql?: Rate | null; heldout?: ScoreTotals | null };
/** The round as the loop figure draws it (eval/rounds.stages): the counts on each stage. */
export type Stages = {
  run: { agent: string | null; run_id: string; trials: number; totals: ScoreTotals | null; cost_usd: number | null };
  diagnose: { goldened: number; sql_fails: number; ledger: boolean; breaks: Partial<Record<Component, number>>; categories: Record<string, number> };
  split: { sizes: { train: number; heldout: number } | null; read: number; heldout_sql: Rate | null; read_all?: boolean };
  sessions: { dataset: number; component: number; system: number; cost_usd: number | null; model: string | null };
  guard: { writes: number; refused: number; leaks: number; too_long: number; accepted: number; dropped: number; caps: { notes: number; section: number | null; system_md: number } | null };
  version: { name: string; notes: number; sections: number; system_md_chars: number | null; system_md_changed: boolean | null; plan_first: boolean; fingerprint: string | null; prompt_version: number | null };
  outcome: { run_id: string | null; totals: ScoreTotals | null; heldout_sql: Rate | null; promoted_at: string | null };
};
export type Rounds = { champion: string; rounds: RoundSummary[]; versions: VersionNode[] };
export type Side = {
  answer: boolean | null;
  sql: boolean | null;
  decision: boolean | null;
  category: string;
  mode: string | null;
  breaks_at?: Component | null;
  why?: string;
  verdicts?: Record<Component, Verdict> | null;
  golden_lines?: Lines | null;
  agent_lines?: Lines | null;
  plan?: Lines | null;
};
export type Change = 'improved' | 'regressed' | 'held' | 'still failing' | 'not scored';
export type QuestionChange = { query_id: string; dataset: string; question: string; split: string | null; read: boolean; before: Side | null; after: Side | null; change: Change; sql_change?: Change };
export type Attempt = { ok: boolean; chars: number | null; problems: string[] };
export type Review = { reviewed: boolean; decisive?: boolean; question?: string; what?: string; reason?: string; cost_usd?: number | null; error?: string | null };
export type OptimiseSessionRec = {
  scope: string;
  kind?: 'dataset' | 'component' | 'system';
  notes: string | null;
  rationale: string;
  refusals: { problems: string[]; notes_chars?: number; rationale_chars?: number; redacted?: boolean }[];
  attempts?: Attempt[];
  budget?: number | null;
  dropped?: boolean;
  questions: string[];
  n_turns: number;
  cost_usd: number | null;
  error: string | null;
  duration_ms?: number;
  /** s11 G1: the reviewer's verdict on each write that passed the literal guard. */
  reviews?: Review[];
};
export type RoundDetail = {
  summary: RoundSummary;
  components?: { name: Component; what: string }[];
  record: {
    version: string;
    challenger_of: string;
    source_run: string;
    started_at: string;
    optimiser: { model: string; effort: string };
    split: { train: number; heldout: number };
    cost_usd: number;
    sessions: OptimiseSessionRec[];
    system_md_changed: boolean;
    method?: string;
    playbook?: Partial<Record<Component, string[]>>;
    plan_first?: boolean;
    caps?: { notes: number; section: number | null; system_md: number };
    trained_on?: 'train' | 'all' | 'crossfit';
    audit_g2?: { units_with_gold: Record<string, number> };
    playbook_skipped_g3?: Partial<Record<Component, string[]>>;
  };
  diagnostic: { run_id: string; totals: ScoreTotals | null; by_split: Record<string, ScoreTotals> | null; optimise_first: { category: string; n: number; queries: string[] }[]; categories: Record<string, number> };
  questions: QuestionChange[];
  outcome: { all: Tally; by_split: Record<string, Tally>; by_dataset: Record<string, Tally>; category_moves: { from: string; to: string; n: number }[] } | null;
  files: { name: string; added: boolean; diff: GoldDiffLine[] }[];
};
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
  agent_sql?: string | null;
  agent_result?: string | null;
  mode?: string | null;
  step?: string | null;
  score?: ScoreRow | null;
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
  submission?: AgentSubmission | null;
  score?: ScoreRow | null;
  golden?: GoldenBriefSql | null;
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
