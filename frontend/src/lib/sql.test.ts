import { describe, expect, it } from 'vitest';
import { highlightLines } from './sql';

describe('highlightLines (CodeMirror SQL grammar, Postgres dialect)', () => {
  const sql = `-- top repos\nWITH r AS (SELECT "Name", count(*)::int AS n FROM t WHERE s ILIKE '%it''s%' AND x >= 3.5)\nselect * from r order by n desc limit 5;`;
  const lines = highlightLines(sql);
  const spans = lines.flat();
  const cls = (text: string) => spans.find((s) => s.text === text)?.cls;

  it('gives back the input exactly, line for line', () => {
    expect(lines.map((l) => l.map((s) => s.text).join('')).join('\n')).toBe(sql);
    expect(lines).toHaveLength(3);
  });

  it('colours keywords, functions, strings, numbers, comments and quoted names apart', () => {
    expect(cls('-- top repos')).toBe('sq-com');
    expect(cls('WITH')).toBe('sq-kw');
    expect(cls('select')).toBe('sq-kw');
    expect(cls('count')).toBe('sq-fn');
    expect(cls("'%it'")).toBe('sq-str'); // an escaped quote splits the literal; both halves are strings
    expect(cls("'s%'")).toBe('sq-str');
    expect(cls('3.5')).toBe('sq-num');
    expect(cls('"Name"')).toBe('sq-id');
  });

  it('never loses a character on unterminated input', () => {
    for (const s of ["select 'open", 'select "open', 'select /* open'])
      expect(
        highlightLines(s)
          .map((l) => l.map((x) => x.text).join(''))
          .join('\n'),
      ).toBe(s);
  });
});
