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
