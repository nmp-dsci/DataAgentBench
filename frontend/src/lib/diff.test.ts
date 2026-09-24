import { describe, expect, it } from 'vitest';
import type { GoldDiffLine } from './api';
import { diffStat, foldDiff, splitRows } from './diff';

const eq = (n: number): GoldDiffLine => ({ op: 'eq', gold: n, result: n, text: `r${n}` });
const del = (n: number): GoldDiffLine => ({ op: 'del', gold: n, result: null, text: `g${n}`, changed: [1] });
const add = (n: number): GoldDiffLine => ({ op: 'add', gold: null, result: n, text: `x${n}`, changed: [1] });

describe('foldDiff', () => {
  it('keeps three unchanged lines either side of a change and folds the rest', () => {
    const lines = [...Array.from({ length: 10 }, (_, k) => eq(k + 1)), del(11), add(11), ...Array.from({ length: 10 }, (_, k) => eq(k + 12))];
    const items = foldDiff(lines);
    expect(items.map((i) => (i.kind === 'fold' ? `fold${i.lines.length}` : i.line.op))).toEqual([
      'fold7', 'eq', 'eq', 'eq', 'del', 'add', 'eq', 'eq', 'eq', 'fold7',
    ]);
  });

  it('does not fold a run that is barely longer than its context', () => {
    const lines = [del(1), eq(2), eq(3), eq(4), eq(5), eq(6), eq(7), eq(8), add(9)];
    expect(foldDiff(lines).every((i) => i.kind === 'line')).toBe(true);
  });
});

describe('splitRows', () => {
  it('zips a hunk of removed and added lines, and pads the longer side', () => {
    const rows = splitRows([eq(1), del(2), del(3), add(2), eq(4)]);
    expect(rows.map((r) => [r.gold?.text ?? null, r.result?.text ?? null])).toEqual([
      ['r1', 'r1'],
      ['g2', 'x2'],
      ['g3', null],
      ['r4', 'r4'],
    ]);
  });
});

it('diffStat counts added and removed lines', () => {
  expect(diffStat([eq(1), del(2), add(2), add(3)])).toEqual({ added: 2, removed: 1 });
});
