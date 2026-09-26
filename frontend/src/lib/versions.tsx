import type { KeyboardEvent } from 'react';
import type { Rate as RateT, Reign, VersionChange, VersionNode } from './api';

/** How a version was made, as the figure names it under each version. */
export const CHANGE_LABEL: Record<VersionChange['kind'], string> = {
  round: 'optimise',
  build: 'build change',
  model: 'model change',
  base: 'base',
};

const r = (x: RateT | null | undefined) => (x ? `${x.passed}/${x.n}` : '—');

const onKey = (go: () => void) => (e: KeyboardEvent) => {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    go();
  }
};

/** Every version in the order its newest complete full-split run started. */
export function versionOrder(nodes: VersionNode[]): VersionNode[] {
  return [...nodes].sort((a, b) => (a.started_at ?? '9').localeCompare(b.started_at ?? '9'));
}

/**
 * Fig · every version in order, one column each, and under it how that version was made:
 * an optimise round, a build change or a model change (from `/api/optimise`, `change`).
 * `rounds` plots SQL passed (filled) and answers passed (open), the Optimise tab's view;
 * `champion` plots answers passed and joins the versions that held the title, the Runs tab's.
 */
export function VersionsFig({
  nodes,
  champion,
  mode,
  reigns = [],
  open = null,
  onPick,
}: {
  nodes: VersionNode[];
  champion: string;
  mode: 'rounds' | 'champion';
  reigns?: Reign[];
  open?: string | null;
  onPick: (n: VersionNode) => void;
}) {
  const order = versionOrder(nodes);
  const W = Math.max(1000, 140 + order.length * 104);
  const H = 360;
  const lx = 64;
  const rx = W - 30;
  const top = 40;
  const bot = 220;
  const gap = order.length > 1 ? (rx - lx - 100) / (order.length - 1) : 0;
  const X = (i: number) => (order.length > 1 ? lx + 50 + i * gap : (lx + rx) / 2);
  const Y = (share: number) => bot - (bot - top) * share;
  const share = (x: RateT | null | undefined) => (x && x.n ? x.passed / x.n : null);
  const ans = order.map((n) => (n.passed != null && n.scored ? n.passed / n.scored : null));
  const sql = order.map((n) => share(n.sql));
  const reignOf = new Map(reigns.map((x) => [x.version, x]));
  const champs = order.map((n, i) => (reignOf.has(n.version) && ans[i] != null ? i : -1)).filter((i) => i >= 0);
  const line = (vals: (number | null)[], at: number[]) =>
    at
      .filter((i) => vals[i] != null)
      .map((i) => `${X(i)},${Y(vals[i] as number)}`)
      .join(' ');
  const all = order.map((_, i) => i);
  const aria =
    mode === 'rounds'
      ? 'Every agent version in order, with the share of SQL passed and of answers passed on its newest complete run; under each version, how it was made: an optimise round, a build change or a model change'
      : `Every agent version in order, answers passed on its newest complete run; a solid line joins the versions that held the title, from ${order[0]?.version ?? ''} to ${champion}; under each version, how it was made: an optimise round, a build change or a model change`;
  return (
    <div className="figscroll">
      <svg className="dia" viewBox={`0 0 ${W} ${H}`} style={{ minWidth: Math.ceil(W * 0.985) }} role="img" aria-label={aria}>
        <title>{mode === 'rounds' ? 'SQL and answers per version' : 'The champion over the versions'}</title>
        {[0, 0.25, 0.5, 0.75, 1].map((g) => (
          <g key={g}>
            <line className="ax" x1={lx} x2={rx} y1={Y(g)} y2={Y(g)} style={{ strokeDasharray: g ? '2 4' : undefined }} />
            <text className="tx k" x={lx - 8} y={Y(g) + 4} textAnchor="end">
              {g * 100}%
            </text>
          </g>
        ))}
        {mode === 'rounds' ? (
          <>
            <polyline fill="none" style={{ stroke: 'var(--ink-2)', strokeDasharray: '5 4', strokeWidth: 1.5 }} points={line(ans, all)} />
            <polyline fill="none" style={{ stroke: 'var(--accent)', strokeWidth: 2.5 }} points={line(sql, all)} />
          </>
        ) : (
          champs.length > 1 && <polyline fill="none" style={{ stroke: 'var(--accent)', strokeWidth: 3 }} points={line(ans, champs)} />
        )}
        {order.map((n, i) => {
          const ch = n.change;
          const reign = reignOf.get(n.version);
          const go = () => onPick(n);
          const ho = n.heldout?.sql;
          const lift = reign?.lift != null ? ` (${reign.lift >= 0 ? '+' : '−'}${Math.abs(reign.lift)})` : '';
          return (
            <g key={n.version} id={`ver-${n.version}`} className="pick" role="button" tabIndex={0} aria-label={`${n.version}: answers ${n.passed ?? '—'} of ${n.scored ?? '—'}, SQL ${r(n.sql)}${ch ? `; ${CHANGE_LABEL[ch.kind]}, ${ch.detail}` : ''}`} onClick={go} onKeyDown={onKey(go)}>
              <title>
                {n.version} ({n.model ?? '—'}): answers {n.passed ?? '—'}/{n.scored ?? '—'} · SQL {r(n.sql)} · held-out SQL {r(ho)}
                {mode === 'champion' ? (reign ? ' · held the title' : ' · did not take the title') : ''}
                {ch?.note ? `\n${ch.note}` : ''}
              </title>
              {mode === 'rounds' ? (
                <>
                  {ans[i] != null && (
                    <>
                      <circle cx={X(i)} cy={Y(ans[i] as number)} r={6} style={{ fill: 'var(--panel)', stroke: 'var(--ink-2)', strokeWidth: 2 }} />
                      <text className="tx k" x={X(i)} y={Y(ans[i] as number) - 13} textAnchor="middle">
                        {n.passed}/{n.scored}
                      </text>
                    </>
                  )}
                  {sql[i] != null && (
                    <>
                      <circle cx={X(i)} cy={Y(sql[i] as number)} r={7} style={{ fill: 'var(--accent)' }} />
                      {/* centred under the point on two lines, so neighbours a question apart never collide */}
                      <text className="tx k" x={X(i)} y={Y(sql[i] as number) + 24} textAnchor="middle" style={{ fill: 'var(--ink)' }}>
                        SQL {r(n.sql)}
                      </text>
                      {ho && (
                        <text className="tx k" x={X(i)} y={Y(sql[i] as number) + 40} textAnchor="middle">
                          ho {r(ho)}
                        </text>
                      )}
                    </>
                  )}
                </>
              ) : (
                ans[i] != null && (
                  <>
                    <circle cx={X(i)} cy={Y(ans[i] as number)} r={reign ? 8 : 6} style={reign ? { fill: 'var(--accent)' } : { fill: 'var(--panel)', stroke: 'var(--ink-2)', strokeWidth: 2 }} />
                    <text className="tx k" x={X(i)} y={reign ? Y(ans[i] as number) - 16 : Y(ans[i] as number) + 26} textAnchor="middle" style={reign ? { fill: 'var(--accent)' } : undefined}>
                      {n.passed}/{n.scored}
                      {lift}
                    </text>
                  </>
                )
              )}
              <text className="tx" x={X(i)} y={bot + 26} textAnchor="middle" style={open === n.version || n.version === champion ? { fontWeight: 700 } : undefined}>
                {n.version}
                {n.version === champion ? ' ★' : ''}
              </text>
              <text className="tx s" x={X(i)} y={bot + 44} textAnchor="middle">
                {n.model ?? ''}
              </text>
              {ch && (
                <g className="chg">
                  {ch.kind !== 'base' && (
                    <line x1={X(i) - 26} x2={X(i) + 26} y1={bot + 62} y2={bot + 62} style={{ stroke: ch.kind === 'round' ? 'var(--accent)' : 'var(--line-3)', strokeDasharray: ch.kind === 'round' ? undefined : '4 3', strokeWidth: 2 }} />
                  )}
                  <text className="tx" x={X(i)} y={bot + 84} textAnchor="middle" style={ch.kind === 'round' ? { fill: 'var(--accent)' } : undefined}>
                    {CHANGE_LABEL[ch.kind]}
                  </text>
                  <text className="tx s" x={X(i)} y={bot + 102} textAnchor="middle">
                    {ch.detail}
                  </text>
                  {ch.source && (
                    <text className="tx k" x={X(i)} y={bot + 120} textAnchor="middle">
                      from {ch.source}
                    </text>
                  )}
                </g>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
