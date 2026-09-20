import { Link } from 'react-router-dom';
import { type QuerySummary, type Validators as V, STYLE_LABEL, fmtInt, queryPath, useGet } from '../lib/api';
import { Loading, Rate } from '../lib/ui';

const HOW: Record<string, string> = {
  regex: 'strips thousands separators, finds every integer or decimal in the answer, passes if any equals the gold (often with a tolerance)',
  'reads-gold-file': 'loads ground_truth.csv beside it at call time, then matches; none of the 54 in scope does this (all 20 are in the deferred cve and usaspending datasets)',
  substring: 'case-insensitive containment; list golds require every item, and one (googlelocal/1) requires the order',
  levenshtein: 'fuzzy-matches each gold name against the answer with a pure-Python O(n·m) edit distance; seconds per call on long answers, which is why the rescore has a timeout',
};

export function Validators() {
  const { data: v, error } = useGet<V>('/api/validators');
  const { data: qs } = useGet<QuerySummary[]>('/api/queries');
  if (!v) return <Loading error={error} />;
  const total = v.styles.reduce((n, s) => n + s.n, 0);
  const inline = total - v.reads_gold_file.length;
  const byId = new Map((qs ?? []).map((q) => [q.id, q]));
  return (
    <>
      <p className="label">validators · {total} files · {fmtInt(v.total_lines)} lines</p>
      <h1>
        {inline} of {total} validators carry the answer <em>inline</em> in Python; the CSV beside them is a copy
      </h1>
      <p className="lead">
        A query's <code>validate.py</code> is the eval. It is arbitrary Python with one function, <code>validate(llm_output) → (bool, reason)</code>, and the benchmark runs it on the
        agent's final answer string. Four styles cover all of them; the style decides how much prose an agent can wrap around the right value and still pass.
      </p>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>Style</th>
              <th className="num">Queries</th>
              <th>How it judges</th>
              <th className="num">Longest</th>
              <th>Published pass rate over its queries</th>
            </tr>
          </thead>
          <tbody>
            {v.styles.map((s) => (
              <tr key={s.style} className={s.n === 0 ? 'dim' : ''}>
                <td className="sub">{STYLE_LABEL[s.style] ?? s.style}</td>
                <td className="num">{s.n}</td>
                <td className="wrap">{HOW[s.style]}</td>
                <td className="num">{s.longest ? `${s.longest} lines` : '—'}</td>
                <td>
                  <Rate passed={s.trials?.passed} n={s.trials?.n} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {v.styles
        .filter((s) => s.n > 0)
        .map((s) => (
          <section key={s.style}>
            <h2>
              {STYLE_LABEL[s.style] ?? s.style} — {s.n} {s.n === 1 ? 'query' : 'queries'}
            </h2>
            <div className="tw">
              <table>
                <thead>
                  <tr>
                    <th>Query</th>
                    <th>Question</th>
                    <th className="num">Gold lines</th>
                    <th className="num">Validator lines</th>
                    <th>Published pass rate</th>
                  </tr>
                </thead>
                <tbody>
                  {s.ids.map((id) => {
                    const q = byId.get(id);
                    return (
                      <tr key={id}>
                        <td className="sub">
                          <Link to={queryPath(id)}>{id}</Link>
                        </td>
                        <td className="q wrap">{q ? (q.question.length > 160 ? `${q.question.slice(0, 160)}…` : q.question) : ''}</td>
                        <td className="num">{q?.gold_lines ?? '—'}</td>
                        <td className="num">{q?.validator_lines ?? '—'}</td>
                        <td>
                          <Rate passed={q?.trials?.passed} n={q?.trials?.n} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        ))}
    </>
  );
}
