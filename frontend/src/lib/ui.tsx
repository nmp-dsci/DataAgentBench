import { useState } from 'react';
import { Link } from 'react-router-dom';
import { type DatasetSummary, fmtPct, queryPath, useGet } from './api';

/** Every dataset as a lozenge, in the order the cards use. `current` is unset on the index: nothing is selected there. */
export function DatasetChips({ current }: { current?: string }) {
  const { data: ds } = useGet<DatasetSummary[]>('/api/datasets');
  if (!ds) return null;
  const order = ds.slice().sort((a, b) => b.n_queries - a.n_queries || a.key.localeCompare(b.key));
  return (
    <nav className="chips datasetbar" aria-label="datasets">
      {order.map((d) => (
        <Link key={d.key} to={`/datasets/${d.key}`} className={`chip nav ${d.key === current ? 'on' : ''}`} aria-current={d.key === current ? 'page' : undefined}>
          {d.key}
          <span className="n">{d.n_queries}</span>
        </Link>
      ))}
    </nav>
  );
}

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
/** Long text clipped at `at` characters, with a toggle that opens the rest in place. */
export function Clip({ text, at }: { text: string; at: number }) {
  const [open, setOpen] = useState(false);
  if (text.length <= at) return <>{text}</>;
  return (
    <>
      {open ? text : `${text.slice(0, at).trimEnd()}…`}
      <button type="button" className="more" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {open ? 'less' : 'more'}
      </button>
    </>
  );
}

/** The gold answer in a cell: its first line, and — when `full` is given — a toggle that opens every line. */
export function Gold({ preview, lines, full }: { preview: string; lines: number; full?: string }) {
  const [open, setOpen] = useState(false);
  const first = preview.split('\n')[0] ?? '';
  const cut = first.length > 60;
  const head = cut ? `${first.slice(0, 60)}…` : first;
  const more = lines > 1 ? `+${lines - 1} more line${lines === 2 ? '' : 's'}` : cut ? 'show all' : null;
  if (!full || !more) {
    return (
      <span className="gold-cell mono" title={full ?? preview}>
        {head}
        {more && <span className="path">{more}</span>}
      </span>
    );
  }
  return (
    <span className="gold-cell mono">
      {open ? <pre className="gold-full">{full}</pre> : head}
      <button type="button" className="more" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {open ? 'show less' : more}
      </button>
    </span>
  );
}
