import { useState } from 'react';
import type { GoldDiffLine } from './api';
import { diffStat, foldDiff, splitRows } from './diff';

/** A line's cells, the differing ones marked (cells are the comma-separated values the gold match compares). */
function Cells({ l }: { l: GoldDiffLine }) {
  if (!l.changed?.length) return <>{l.text}</>;
  const changed = new Set(l.changed);
  return (
    <>
      {l.text.split(',').map((c, i) => (
        <span key={i}>
          {i > 0 && ','}
          {changed.has(i) ? <mark>{c}</mark> : c}
        </span>
      ))}
    </>
  );
}

const MARK = { eq: ' ', del: '−', add: '+' } as const;

/** The result against the gold, like a code review: gold lines the result lacks (−), result lines the gold lacks (+).
 *  `a` and `b` name the two sides (the gold and a result; or a golden's result and an agent's). */
export function GoldDiff({ lines, a = 'gold', b = 'result' }: { lines: GoldDiffLine[]; a?: string; b?: string }) {
  const [split, setSplit] = useState(false);
  const [open, setOpen] = useState<Set<number>>(new Set());
  const { added, removed } = diffStat(lines);
  const unified = (ls: GoldDiffLine[]) =>
    ls.map((l, i) => (
      <tr key={`u${l.gold}-${l.result}-${i}`} className={l.op}>
        <td className="ln">{l.gold ?? ''}</td>
        <td className="ln">{l.result ?? ''}</td>
        <td className="mk">{MARK[l.op]}</td>
        <td className="tx">
          <Cells l={l} />
        </td>
      </tr>
    ));
  const side = (ls: GoldDiffLine[]) =>
    splitRows(ls).map((r, i) => (
      <tr key={`s${r.gold?.gold}-${r.result?.result}-${i}`}>
        <td className="ln">{r.gold?.gold ?? ''}</td>
        <td className={`tx ${!r.gold ? 'blank' : r.gold.op === 'eq' ? '' : 'del'}`}>{r.gold && <Cells l={r.gold} />}</td>
        <td className="ln">{r.result?.result ?? ''}</td>
        <td className={`tx ${!r.result ? 'blank' : r.result.op === 'eq' ? '' : 'add'}`}>{r.result && <Cells l={r.result} />}</td>
      </tr>
    ));
  // runs of shown lines between folds; a fold is one row until it is opened (folds hold only unchanged lines, so no hunk is cut)
  const body = (render: (ls: GoldDiffLine[]) => JSX.Element[]) => {
    const out: JSX.Element[] = [];
    let run: GoldDiffLine[] = [];
    const flush = () => {
      out.push(...render(run));
      run = [];
    };
    foldDiff(lines).forEach((it, k) => {
      if (it.kind === 'line') run.push(it.line);
      else if (open.has(k)) run.push(...it.lines);
      else {
        flush();
        out.push(
          <tr key={`f${k}`} className="fold">
            <td colSpan={4}>
              <button type="button" className="linkish" onClick={() => setOpen((o) => new Set(o).add(k))}>
                ⋯ {it.lines.length} unchanged line{it.lines.length === 1 ? '' : 's'}
              </button>
            </td>
          </tr>,
        );
      }
    });
    flush();
    return out;
  };
  return (
    <div className="code golddiff">
      <div className="golddiff-head">
        <p className="label">diff against the {a}</p>
        <span className="stat">
          <span className="add">+{added}</span> <span className="del">−{removed}</span>
        </span>
        <span className="small muted">
          − in the {a}, not in the {b} · + in the {b}, not in the {a} · changed cells marked
        </span>
        <span className="seg" role="group" aria-label="diff layout">
          <button type="button" className={split ? '' : 'on'} aria-pressed={!split} onClick={() => setSplit(false)}>
            Unified
          </button>
          <button type="button" className={split ? 'on' : ''} aria-pressed={split} onClick={() => setSplit(true)}>
            Split
          </button>
        </span>
      </div>
      <div className="golddiff-scroll">
        <table className={split ? 'split' : 'unified'}>
          {split && (
            <thead>
              <tr>
                <th colSpan={2}>{a}</th>
                <th colSpan={2}>{b}</th>
              </tr>
            </thead>
          )}
          <tbody>{body(split ? side : unified)}</tbody>
        </table>
      </div>
    </div>
  );
}
