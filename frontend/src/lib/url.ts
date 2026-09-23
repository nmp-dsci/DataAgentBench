/**
 * One address per thing. Every explorer URL is built here, from three rules:
 *
 * 1. One id, the same string everywhere. Dataset `deps_dev_v1`, question
 *    `deps_dev_v1/1` (as the index and every table print it), trial
 *    `deps_dev_v1/1/t1`, run `20260921T064521Z_v0_all_haiku`, agent version
 *    `champion`, submission `lb:permute_eq`. In a path the id's slashes are path
 *    separators, so an address can be chopped back one level at a time. The trace
 *    file name (`deps_dev_v1_1_t1.json`) stays on disk and never reaches a URL.
 * 2. The path names the subject; the query string holds the lens. If dropping a
 *    value leaves nothing to show, it is the subject (a dataset, question, run,
 *    trial, agent version) and goes in the path. If dropping it falls back to a
 *    default (a selected node, a replayed trial, a compare grouping), it is a lens.
 * 3. Picking from a list opens the detail in place: a nested route renders into
 *    the list page's <Outlet>, so the address changes and the list stays.
 *
 * The backend mirror is `trial_id` / `trace_stem` in `dab_bench/data/aliases.py`.
 */

import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';

export type Lens = Record<string, string | null | undefined>;

// ── ids ───────────────────────────────────────────────────────────────────
export function trialId(r: { query_id: string; trial: number }): string {
  return `${r.query_id}/t${r.trial}`;
}

/** `deps_dev_v1/1/t1` → its parts, or null when it is not a trial id. */
export function parseTrialId(id: string): { queryId: string; dataset: string; n: number; trial: number } | null {
  const m = /^([a-z0-9_]+)\/(\d+)\/t(\d+)$/.exec(id);
  return m ? { queryId: `${m[1]}/${Number(m[2])}`, dataset: m[1], n: Number(m[2]), trial: Number(m[3]) } : null;
}

/** The pre-grammar spelling, the trace file's stem `deps_dev_v1_1_t1`, → `deps_dev_v1/1/t1`.
 *  Unambiguous without the dataset list: the suffix `_<n>_t<k>` is anchored at the end. */
export function trialIdFromStem(stem: string): string | null {
  const m = /^([a-z0-9_]+?)_(\d+)_t(\d+)$/.exec(stem);
  return m ? `${m[1]}/${Number(m[2])}/t${Number(m[3])}` : null;
}

// ── paths ─────────────────────────────────────────────────────────────────
export const datasetPath = (ds: string): string => `/datasets/${ds}`;
/** A question lives under its dataset: `/datasets/deps_dev_v1/1`. */
export const questionPath = (queryId: string): string => `/datasets/${queryId}`;
export const runPath = (runId: string, lens?: Lens): string => `/runs/${runId}${search(lens)}`;
/** One trial of one run: `/runs/<run>/deps_dev_v1/1/t1`. */
export const trialPath = (runId: string, tid: string): string => `/runs/${runId}/${tid}`;
export const goldenPath = (queryId?: string): string => (queryId ? `/golden/${queryId}` : '/golden');
export const agentPath = (version: string, lens?: Lens): string => `/agent/${version}${search(lens)}`;
export const runsPath = (lens?: Lens): string => `/runs${search(lens)}`;

// ── the API's mirror of the same ids ───────────────────────────────────────
export const apiTrialPath = (runId: string, tid: string): string => `/api/runs/${runId}/${tid}`;

// ── the lens ──────────────────────────────────────────────────────────────
/** Escape a query-string value, but leave `/`, `:` and `,` readable (all legal in a
 *  query per RFC 3986 §3.4), so a lens reads `trial=deps_dev_v1/1/t1&node=tool:query_db`.
 *  `URLSearchParams.toString()` would write `deps_dev_v1%2F1%2Ft1` and `tool%3Aquery_db`. */
function enc(v: string): string {
  return encodeURIComponent(v).replace(/%2F/gi, '/').replace(/%3A/gi, ':').replace(/%2C/gi, ',');
}

/** `?a=1&b=x/y`, skipping empty values; '' when nothing is set. Keys keep their given order. */
export function search(lens?: Lens): string {
  const parts = Object.entries(lens ?? {})
    .filter((e): e is [string, string] => e[1] != null && e[1] !== '')
    .map(([k, v]) => `${enc(k)}=${enc(v)}`);
  return parts.length ? `?${parts.join('&')}` : '';
}

/** The current lens with `patch` applied (null or '' removes a key), as a `?…` string. */
export function patchLens(current: URLSearchParams, patch: Lens): string {
  const next: Lens = Object.fromEntries(current.entries());
  for (const [k, v] of Object.entries(patch)) next[k] = v;
  return search(next);
}

/** The page's lens and a setter that rewrites it in place (replace, not push), readable. */
export function useLens(): [URLSearchParams, (patch: Lens) => void] {
  const [sp] = useSearchParams();
  const nav = useNavigate();
  const { pathname, hash } = useLocation();
  const set = (patch: Lens) => nav({ pathname, search: patchLens(sp, patch), hash }, { replace: true });
  return [sp, set];
}
