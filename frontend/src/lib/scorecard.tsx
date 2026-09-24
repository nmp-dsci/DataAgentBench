import type { GoldenBriefSql, Rate, ScoreRow, ScoreTotals } from './api';
import { GoldDiff } from './golddiff';
import { SqlBlock } from './sql';

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

/** What each failure category means, in a sentence a reader can act on. */
export const CATEGORY_HELP: Record<string, string> = {
  solved: 'The SQL returns the golden result, with the right mode, and the validator passes.',
  'no golden': 'No golden SQL yet, so only the answer is scored; the question sits outside the optimisation loop.',
  'no SQL': 'The agent never submitted a statement: it ran out of turns, or answered in plain text.',
  'SQL error': 'The submitted SQL failed when the harness re-ran it.',
  decision: 'The result was right, but the agent chose the wrong mode (pass-through vs derived).',
  'derived step wrong': 'The SQL returned the right evidence, but the answer the agent read from it is wrong.',
  format: "The result is the golden's, but the validator rejects how the answer is written.",
  'right answer another way': "The validator passes, but the rows differ from the golden's (extra rows or columns, other formatting).",
  'wrong tables': 'The agent read a different set of tables from the golden.',
  'join differs': 'The agent joined on different keys, or matched fuzzily where the golden uses an exact key.',
  'parse differs': 'The agent pulled values out of text with a different pattern from the golden.',
  'filter differs': 'The agent filtered on different values (WHERE / HAVING).',
  aggregation: 'The agent aggregated or grouped differently.',
  'order / tie': 'The agent ranked, limited or broke ties differently (ORDER BY / LIMIT).',
  'result differs': 'The statements look alike, but the results differ.',
};

const verdictWord = (v: boolean | null | undefined) => (v == null ? 'not scored' : v ? 'pass' : 'fail');

/** The agent's submitted SQL beside the question's golden SQL: the three checks as a table (what each
 *  compares, its verdict, why), the failure category in words, then the two statements and what differs.
 *  Nothing here ever reaches an agent; the scorecard is read after the run. */
export function SqlVersus({ score, agentSql, golden, mode, step, reason }: { score: ScoreRow; agentSql: string | null | undefined; golden: GoldenBriefSql | null | undefined; mode?: string | null; step?: string | null; reason?: string | null }) {
  const structure = Object.entries(score.structure ?? {});
  const solved = score.category === 'solved';
  const noGolden = score.golden_id == null;
  const rows: { key: string; check: string; compares: string; v: boolean | null; why: string }[] = [
    { key: 'answer', check: 'Answer', compares: "the question's own validator on the submitted answer (the leaderboard's score)", v: score.answer, why: reason || '—' },
    {
      key: 'sql',
      check: 'SQL',
      compares: "does the agent's SQL, re-run, return the golden SQL's rows (any row or column order, any column names)",
      v: score.sql,
      why: noGolden ? 'no golden to compare with' : score.sql_detail || (score.sql == null ? 'no SQL submitted' : score.detail),
    },
    {
      key: 'decision',
      check: 'Decision',
      compares: 'pass_through (the result is the answer) or derived (the answer is read from the result); the golden says which is right',
      v: score.decision,
      why: noGolden ? 'no golden to compare with' : score.decision_detail || (mode ? `chose ${mode}` : 'no mode: nothing was submitted'),
    },
  ];
  return (
    <div className="versus">
      <div className="tw">
        <table className="checks">
          <thead>
            <tr>
              <th>Check</th>
              <th>What it compares</th>
              <th>Verdict</th>
              <th>Why</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}>
                <td className="sub">{r.check}</td>
                <td className="small">{r.compares}</td>
                <td>
                  <span className={`chip ${r.v == null ? '' : r.v ? 'ok' : 'warn'}`}>{verdictWord(r.v)}</span>
                </td>
                <td className="small">{r.why}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="diagnosis">
        <span className="label">diagnosis</span> <b>{solved ? 'solved the golden way' : score.category}</b>
        {' — '}
        {CATEGORY_HELP[score.category] ?? score.detail}
        {score.split && <> This is {score.split === 'heldout' ? 'a held-out question: the optimiser never sees it.' : 'a training question: the optimiser may read it.'}</>}
      </p>
      <div className="compare">
        {agentSql ? (
          <SqlBlock sql={agentSql} label={`agent · ${mode ?? 'no submit'}${step ? ` · step: ${step}` : ''}`} />
        ) : (
          <div className="code">
            <p className="label">agent SQL</p>
            <pre>(no SQL submitted)</pre>
          </div>
        )}
        {golden ? (
          <SqlBlock sql={golden.sql} band label={`golden #${golden.id} · ${golden.kind} · saved ${golden.created_at.slice(0, 10)}`} />
        ) : (
          <div className="code band">
            <p className="label">{score.golden_id ? `golden #${score.golden_id}` : 'no golden'}</p>
            <pre>{score.golden_id ? '(the database is unreachable; the golden SQL is in the Golden tab)' : '—'}</pre>
          </div>
        )}
      </div>
      {structure.length > 0 && (
        <div className="tw">
          <table className="structure">
            <caption>How the two statements differ (parsed with sqlglot); the first row names the category</caption>
            <thead>
              <tr>
                <th>Part of the SQL</th>
                <th>Golden</th>
                <th>Agent</th>
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
