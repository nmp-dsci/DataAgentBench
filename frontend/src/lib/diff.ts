import type { GoldDiffLine } from './api';

/**
 * The gold-vs-result diff, laid out the way a code review shows one. The backend
 * (`golden.gold_diff`) decides which lines match, with the gold match's own rules; this
 * only folds long unchanged runs and pairs lines for the side-by-side view.
 */

export type DiffItem = { kind: 'line'; line: GoldDiffLine } | { kind: 'fold'; lines: GoldDiffLine[] };

/** Keep `context` unchanged lines around every change; fold longer runs into one expandable row. */
export function foldDiff(lines: GoldDiffLine[], context = 3): DiffItem[] {
  const out: DiffItem[] = [];
  let i = 0;
  while (i < lines.length) {
    if (lines[i].op !== 'eq') {
      out.push({ kind: 'line', line: lines[i++] });
      continue;
    }
    let j = i;
    while (j < lines.length && lines[j].op === 'eq') j++;
    const run = lines.slice(i, j);
    const keepHead = i === 0 ? 0 : context; // after a change
    const keepTail = j === lines.length ? 0 : context; // before a change
    if (run.length > keepHead + keepTail + 1) {
      run.slice(0, keepHead).forEach((line) => out.push({ kind: 'line', line }));
      out.push({ kind: 'fold', lines: run.slice(keepHead, run.length - keepTail) });
      run.slice(run.length - keepTail).forEach((line) => out.push({ kind: 'line', line }));
    } else {
      run.forEach((line) => out.push({ kind: 'line', line }));
    }
    i = j;
  }
  return out;
}

export type SplitRow = { gold: GoldDiffLine | null; result: GoldDiffLine | null };

/** Gold on the left, result on the right: equal lines side by side, a hunk's removed and added lines zipped. */
export function splitRows(lines: GoldDiffLine[]): SplitRow[] {
  const rows: SplitRow[] = [];
  let i = 0;
  while (i < lines.length) {
    const l = lines[i];
    if (l.op === 'eq') {
      rows.push({ gold: l, result: l });
      i++;
      continue;
    }
    const dels: GoldDiffLine[] = [];
    const adds: GoldDiffLine[] = [];
    while (i < lines.length && lines[i].op === 'del') dels.push(lines[i++]);
    while (i < lines.length && lines[i].op === 'add') adds.push(lines[i++]);
    for (let k = 0; k < Math.max(dels.length, adds.length); k++) rows.push({ gold: dels[k] ?? null, result: adds[k] ?? null });
  }
  return rows;
}

/** `+n −m`, the counts a review header shows. */
export function diffStat(lines: GoldDiffLine[]): { added: number; removed: number } {
  return { added: lines.filter((l) => l.op === 'add').length, removed: lines.filter((l) => l.op === 'del').length };
}
