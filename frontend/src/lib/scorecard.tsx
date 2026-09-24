import type { GoldenBriefSql, Rate, ScoreRow, ScoreTotals } from './api';
import { GoldDiff } from './golddiff';

/** The scorecard (s06) in the explorer: a question scored three ways, and the agent's SQL beside the golden. */

export const SCORE_COLS = [
  { key: 'answer', label: 'answer', title: "the question's own validator on the submitted answer" },
  { key: 'sql', label: 'SQL', title: "the agent's result against the golden's result (any row or column order)" },
  { key: 'decision', label: 'decision', title: 'pass_through where the golden is an answer, derived where it is evidence' },
] as const;

export function Mark({ v }: { v: boolean | null | undefined }) {
  if (v == null) return <span className="small muted">—</span>;
  return <span className={`chip ${v ? 'ok' : 'warn'}`}>{v ? 'pass' : 'fail'}</span>;
}

export const rate = (r: Rate | undefined) => (r ? `${r.passed}/${r.n}` : '—');

/** `answer 31/54 · SQL 29/49 · decision 46/49`, each with its denominator. */
export function Totals({ t }: { t: ScoreTotals }) {
  return (
    <>
      {SCORE_COLS.map((c, i) => (
        <span key={c.key} title={c.title}>
          {i > 0 && ' · '}
          {c.label} <b>{rate(t[c.key])}</b>
        </span>
      ))}
    </>
  );
}

const ASPECT: Record<string, string> = {
  tables: 'tables read',
  joins: 'join keys',
  patterns: 'text patterns',
  filters: 'filter literals',
  aggregates: 'aggregates',
  grouped: 'grouped',
  order: 'order by',
  limit: 'limit',
  unparsed: 'did not parse',
};

const show = (v: unknown) => (Array.isArray(v) ? (v.length ? v.join(' · ') : '—') : v === '' || v == null ? '—' : String(v));

/** The agent's submitted SQL beside the question's golden SQL: the three scores, the category, what differs in
 *  the statements and in their results. Nothing here ever reaches an agent; the scorecard is read after the run. */
export function SqlVersus({ score, agentSql, golden, mode, step }: { score: ScoreRow; agentSql: string | null | undefined; golden: GoldenBriefSql | null | undefined; mode?: string | null; step?: string | null }) {
  const structure = Object.entries(score.structure ?? {});
  const solved = score.category === 'solved';
  return (
    <div className="versus">
      <p className="verdicts">
        {SCORE_COLS.map((c) => (
          <span key={c.key} title={c.title}>
            {c.label} <Mark v={score[c.key]} />
          </span>
        ))}
        <span className={`chip ${solved ? 'ok' : score.category === 'no golden' ? '' : 'warn'}`}>{solved ? 'solved the golden way' : score.category}</span>
        {score.split && <span className="small muted">{score.split === 'heldout' ? 'held out from the optimiser' : 'a training question'}</span>}
      </p>
      {score.detail && <p className="small">{score.detail}</p>}
      <div className="compare">
        <div className="code">
          <p className="label">
            agent SQL · {mode ?? 'no submit'}
            {step ? ` · step: ${step}` : ''}
          </p>
          <pre>{agentSql || '(no SQL submitted)'}</pre>
        </div>
        <div className="code band">
          <p className="label">{golden ? `golden #${golden.id} · ${golden.kind} · saved ${golden.created_at.slice(0, 10)}` : score.golden_id ? `golden #${score.golden_id}` : 'no golden'}</p>
          <pre>{golden?.sql ?? (score.golden_id ? '(the database is unreachable; the golden SQL is in the Golden tab)' : '—')}</pre>
        </div>
      </div>
      {structure.length > 0 && (
        <div className="tw">
          <table className="structure">
            <thead>
              <tr>
                <th>what differs</th>
                <th>golden</th>
                <th>agent</th>
              </tr>
            </thead>
            <tbody>
              {structure.map(([k, v]) => (
                <tr key={k}>
                  <td className="sub">{ASPECT[k] ?? k}</td>
                  <td className="mono">{typeof v === 'object' && v ? show(v.golden) : show(v)}</td>
                  <td className="mono">{typeof v === 'object' && v ? show(v.agent) : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {(score.result_diff?.length ?? 0) > 0 && <GoldDiff lines={score.result_diff ?? []} a="golden's result" b="agent's result" />}
    </div>
  );
}
