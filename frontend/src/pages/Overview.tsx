import { Link } from 'react-router-dom';
import { type DatasetSummary, type Leaderboard, type Stats, type TrialsIndex, STYLE_LABEL, fmtBytes, fmtInt, fmtPct, shortSha, useGet } from '../lib/api';
import { Kpi, Loading, QLink, Rate } from '../lib/ui';

export function Overview() {
  const { data: s, error } = useGet<Stats>('/api/stats');
  const { data: ds } = useGet<DatasetSummary[]>('/api/datasets');
  const { data: lb } = useGet<Leaderboard>('/api/leaderboard');
  const { data: t } = useGet<TrialsIndex>(s?.rescored ? '/api/trials' : null);
  if (!s) return <Loading error={error} />;

  const rows = (ds ?? []).slice().sort((a, b) => (a.trials?.rate ?? 1) - (b.trials?.rate ?? 1));
  const lbRows = lb?.overallLeaderboard ?? [];
  const best = lbRows[0];
  const worst = lbRows[lbRows.length - 1];
  const tuned = lbRows.filter((r) => r.promptGroup === 'benchmark-informed').length;

  return (
    <>
      <p className="label">DAB · DataAgentBench · UC Berkeley EPIC + Hasura PromptQL · index at {shortSha(s.commit)}</p>
      <h1>
        {s.queries} questions over {s.datasets} datasets, every one with gold, and the <em>evidence</em> for each
      </h1>
      <p className="lead">
        A DAB query is a natural-language question over two to six databases in up to four engines. Every query ships a ground-truth answer
        and its own <code>validate.py</code>. This explorer holds the {s.queries} leaderboard queries with their gold, their validators, the
        authors' schema descriptions and hints, and {fmtInt(s.answer_rows)} published answers judged by those validators.
      </p>

      <div className="kpis">
        <Kpi n={String(s.queries)} b={`queries in ${s.datasets} datasets · ${s.deferred_queries} more in ${s.deferred_datasets.length} unreleased datasets upstream, deferred`} />
        <Kpi n={`${s.with_gold} / ${s.queries}`} b="with a ground_truth.csv and a validate.py" tone="ok" />
        <Kpi
          n={s.rescored ? fmtInt(s.trials_judged) : fmtInt(s.answer_rows)}
          b={s.rescored ? `published answers judged locally · ${s.answer_files} answer files · ${s.never_passed?.length ?? 0} queries never passed` : `published answers in ${s.answer_files} files · not rescored yet`}
          tone={s.rescored ? undefined : 'warn'}
        />
        <Kpi n={fmtBytes(s.bytes_in_scope)} b={`of database files behind the ${s.queries} queries · none downloaded here (${fmtBytes(s.bytes_total)} for all ${s.queries_total_upstream} upstream)`} />
      </div>

      {t && (
        <section>
          <h2>
            {t.summary.under_10pct.length} of {t.summary.queries} queries pass in under 10% of published trials; {t.summary.never_passed.length} never pass
          </h2>
          <p>
            Every committed answer, run through its query's validator ({fmtInt(t.summary.rows)} rows, {t.summary.timed_out} timed out at {t.summary.timeout_s}s). The macro average per answer
            file reproduces the site's Pass@1 to two decimals except on <code>deps_dev_v1</code>, whose validator the site revised after its last re-score.
          </p>
          <div className="chips">
            {t.summary.never_passed.map((id) => (
              <Link key={id} to={`/queries/${id}`} className="chip warn">
                {id} · 0 passes
              </Link>
            ))}
            {t.summary.at_least_95pct.map((id) => (
              <Link key={id} to={`/queries/${id}`} className="chip ok">
                {id} · ≥95%
              </Link>
            ))}
          </div>
          <p className="small">
            <Link to="/queries">All {s.queries} queries, sortable by pass rate →</Link>
          </p>
        </section>
      )}

      <section>
        <h2>
          {rows[0] ? `${rows[0].key} is the hardest dataset for the field` : 'The datasets'}
          {rows[0]?.trials ? ` at ${fmtPct(rows[0].trials.rate)} of ${fmtInt(rows[0].trials.n)} trials` : ''}
        </h2>
        <div className="tw">
          <table>
            <caption>The {s.datasets} datasets, hardest first · pass rate is over every committed trial of the dataset's queries</caption>
            <thead>
              <tr>
                <th>Dataset</th>
                <th className="num">Queries</th>
                <th>Engines</th>
                <th className="num">DB files</th>
                <th>Published pass rate</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.key}>
                  <td className="sub">
                    <Link to={`/datasets/${d.key}`}>{d.key}</Link>
                    <span className="path">{d.folder}</span>
                  </td>
                  <td className="num">{d.n_queries}</td>
                  <td>{d.engines.join(', ')}</td>
                  <td className="num">{fmtBytes(d.bytes_total)}</td>
                  <td>
                    <Rate passed={d.trials?.passed} n={d.trials?.n} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2>The validator is the eval; {s.validator_styles['reads-gold-file'] ?? 0} of {s.queries} read the CSV beside them</h2>
        <p>
          Four ways a query judges an answer. The CSV is a human-readable copy; what passes or fails is the Python.
          Nine use a pure-Python edit distance and can take seconds on a long answer, which is why the rescore runs with a timeout.
        </p>
        <div className="chips">
          {Object.entries(s.validator_styles).map(([k, v]) => (
            <Link key={k} to="/validators" className={`chip ${v === 0 ? 'no' : ''}`}>
              {STYLE_LABEL[k] ?? k} · {v}
            </Link>
          ))}
        </div>
      </section>

      {lb && best && worst && (
        <section>
          <h2>
            {lbRows.length} leaderboard entries from {best.passAt1.toFixed(4)} to {worst.passAt1.toFixed(4)} Pass@1; {tuned} used a DAB-tuned prompt
          </h2>
          <p>
            From the site's own <code>leaderboards.json</code> (updated {lb.updatedAt}). {lb.answer_files.length} of the entries have their answers committed upstream; those are the
            trials this explorer judges per query. <Link to="/leaderboard">The full table →</Link>
          </p>
          <div className="kpis">
            <Kpi n={best.passAt1.toFixed(4)} b={`#1 ${best.agent} · ${best.trials} trials · ${best.date}`} tone="ok" />
            <Kpi n={fmtPct(t?.per_file['react_gemini-3-pro']?.macro ?? null, 2)} b="best plain ReAct baseline (Gemini-3-Pro, 50 trials per query), macro average as the site computes it" />
            <Kpi n={worst.passAt1.toFixed(4)} b={`#${worst.rank} ${worst.agent} · ${worst.trials} trials`} />
          </div>
        </section>
      )}

      {s.deferred_datasets.length > 0 && (
        <p className="small muted" style={{ marginTop: 'var(--s7)' }}>
          {s.deferred_datasets.length} more datasets with {s.deferred_queries} queries exist upstream ({s.deferred_datasets.join(', ')}); none is on the leaderboard or has a published trial, and this
          build records only their count. Never-passed queries here: {s.never_passed?.map((id, i) => <span key={id}>{i ? ', ' : ''}<QLink id={id} /></span>) ?? '—'}.
        </p>
      )}
    </>
  );
}
