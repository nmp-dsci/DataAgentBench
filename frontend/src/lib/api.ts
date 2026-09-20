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
