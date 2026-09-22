import { Link } from 'react-router-dom';
import { fmtPct, queryPath } from './api';

/** A pass rate with its denominator in the same cell, per DESIGN.md: never a bare percentage. */
export function Rate({ passed, n, digits = 0 }: { passed: number | null | undefined; n: number | null | undefined; digits?: number }) {
  if (passed == null || !n) return <span className="muted">not scored</span>;
  const r = passed / n;
  return (
    <span className="ratecell" title={`${passed} of ${n} trials`}>
      <span className="track">
        <i className={r < 0.1 ? 'warn' : ''} style={{ width: `${Math.max(1, r * 100)}%` }} />
      </span>
      <span className="mono">
        {fmtPct(r, digits)} · {passed}/{n}
      </span>
    </span>
  );
}

export function Kpi({ n, b, tone }: { n: string; b: string; tone?: 'ok' | 'warn' }) {
  return (
    <div className="kpi">
      <div className={`n ${tone ?? ''}`}>{n}</div>
      <div className="b">{b}</div>
    </div>
  );
}

export function QLink({ id }: { id: string }) {
  return (
    <Link to={queryPath(id)} className="mono">
      {id}
    </Link>
  );
}

export function Loading({ error }: { error: string | null }) {
  return <p className="empty">{error ? `Could not load: ${error}` : 'Loading…'}</p>;
}

/** The gold answer beside a question, wherever a question is shown: the first line (cut) and how many more, the full text on hover. */
export function Gold({ preview, lines, full }: { preview: string; lines: number; full?: string }) {
  const first = preview.split('\n')[0] ?? '';
  const head = first.length > 60 ? `${first.slice(0, 60)}…` : first;
  return (
    <span className="gold-cell mono" title={full ?? preview}>
      {head}
      {lines > 1 && <span className="path">+{lines - 1} more line{lines === 2 ? '' : 's'}</span>}
    </span>
  );
}
