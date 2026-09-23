import { useEffect } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { type Board, type CompareGroup, type CompareRate, type CompareResp, type Leaderboard, type RunSummary, ROLE_LABEL, STYLE_LABEL, fmtDur, fmtPct, fmtSec, fmtTok, fmtUsd, queryPath, useGet } from '../lib/api';
import { Delta, ProfileTable, Ratios, Role } from '../lib/runs';
import { Loading, Rate } from '../lib/ui';

/** The best plain-ReAct baseline column on the leaderboard's stratified table: the honest bar for a Haiku agent. */
function bestBaseline(lb: Leaderboard | null): { key: string; label: string; overall: number; perDataset: Record<string, number> } | null {
  if (!lb) return null;
  const s = lb.baselineStratified;
  const best = s.columns.reduce<{ key: string; label: string } | null>((b, c) => (b == null || Number(s.overall[c.key]) > Number(s.overall[b.key]) ? c : b), null);
  if (!best) return null;
  const perDataset: Record<string, number> = {};
  for (const r of s.rows) perDataset[String(r.dataset)] = Number(r[best.key]);
  return { ...best, overall: Number(s.overall[best.key]), perDataset };
}

const GROUP_LABEL: Record<CompareGroup, string> = { dataset: 'dataset', style: 'validator style', query: 'query' };

/** One bar per run per group — the focus run above, the challenger below — with the best plain baseline as a tick when grouped by dataset. */
function GroupBars({ cmp, base, label }: { cmp: CompareResp; base: ReturnType<typeof bestBaseline>; label: (id: string) => string }) {
  const ids = [cmp.focus, ...(cmp.challenger ? [cmp.challenger] : [])];
  const rows = cmp.groups;
  if (!rows.length) return null;
  const W = 1000;
  const barH = 13;
  const rowH = ids.length === 2 ? 38 : 26;
  const top = 26;
  const H = top + rows.length * rowH + 8;
  const labelW = cmp.group === 'query' ? 210 : 190;
  const trackW = W - labelW - 90;
  const cls = ['bar hi', 'bar b'];
  const name = (k: string) => (cmp.group === 'style' ? STYLE_LABEL[k] ?? k : k);
  return (
    <figure>
      <p className="label">
        Fig · pass rate by {GROUP_LABEL[cmp.group]} — {ids.map(label).join(' against ')}
        {cmp.challenger && cmp.scope === 'common' ? `, on the ${cmp.common_queries} queries both scored` : ''}
      </p>
      <svg className="dia" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Pass rate by ${GROUP_LABEL[cmp.group]} for ${ids.length} run(s)`}>
        <title>Pass rate by {GROUP_LABEL[cmp.group]}</title>
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <g key={f}>
            <line className="ax" x1={labelW + f * trackW} x2={labelW + f * trackW} y1={top - 6} y2={H - 8} />
            <text className="tx k" x={labelW + f * trackW} y={top - 10} textAnchor="middle">
              {f * 100}%
            </text>
          </g>
        ))}
        {rows.map((g, i) => {
          const y = top + i * rowH;
          const b = cmp.group === 'dataset' ? base?.perDataset[g.key] : undefined;
          return (
            <g key={g.key} id={`grp-${g.key}`}>
              <title>
                {name(g.key)}:{' '}
                {ids
                  .map((id) => {
                    const v = g[id] as CompareRate | undefined;
                    return v ? `${label(id)} ${v.passed}/${v.n} (${fmtPct(v.rate)})` : `${label(id)} not scored`;
                  })
                  .join(' · ')}
                {b != null ? ` · baseline ${fmtPct(b)}` : ''}
              </title>
              <text className="tx" x={labelW - 10} y={y + (ids.length === 2 ? 22 : 17)} textAnchor="end">
                {name(g.key)}
              </text>
              {ids.map((id, j) => {
                const v = g[id] as CompareRate | undefined;
                const yy = y + 4 + j * (barH + 3);
                return (
                  <g key={id}>
                    <rect className="bar" x={labelW} y={yy} width={trackW} height={barH} opacity={0.3} />
                    {v && <rect className={cls[j]} x={labelW} y={yy} width={Math.max(2, v.rate * trackW)} height={barH} />}
                    <text className="tx k" x={labelW + trackW + 8} y={yy + 11}>
                      {v ? `${v.passed}/${v.n}` : 'not scored'}
                    </text>
                  </g>
                );
              })}
              {b != null && <line className="ax mark base" x1={labelW + b * trackW} x2={labelW + b * trackW} y1={y + 1} y2={y + rowH - 4} />}
            </g>
          );
        })}
      </svg>
      <figcaption>
        <span className="sw a" /> {label(cmp.focus)} (focus){cmp.challenger && (
          <>
            {' '}
            · <span className="sw b" /> {label(cmp.challenger)} (challenger)
          </>
        )}
        . A group's rate is the mean per-query pass rate over its queries (passed/trials at the right), the same arithmetic as the run page.
        {cmp.group === 'dataset' && base ? ` The amber tick is ${base.label}, the best plain-ReAct baseline on the leaderboard (${fmtPct(base.overall)} overall).` : ''} Source:{' '}
        <code>runs/&lt;id&gt;/results.jsonl</code> through <code>/api/runs/compare</code>.
      </figcaption>
    </figure>
  );
}

/** Label a run for a picker: agent version first, then what it ran and what it scored. */
function runLabel(r: RunSummary): string {
  const score = r.dry_run ? 'dry run' : `${r.passed ?? 0}/${r.scored ?? 0}`;
  return `${r.agent}@${r.fingerprint.slice(0, 7)} · ${r.split} ${r.n_queries}×${r.trials} · ${score} · ${r.started_at.slice(5, 16).replace('T', ' ')} · ${ROLE_LABEL[r.role]}`;
}

const REMEMBER = 'dab.runs.view';

/** Focus against challenger: pick any two scored runs, group the figure, read every Δ. */
function Compare({ board, base }: { board: Board; base: ReturnType<typeof bestBaseline> }) {
  const [sp, setSp] = useSearchParams();
  useEffect(() => {
    try {
      if ([...sp.keys()].length === 0) {
        const last = sessionStorage.getItem(REMEMBER);
        if (last) setSp(new URLSearchParams(last), { replace: true });
      } else sessionStorage.setItem(REMEMBER, sp.toString());
    } catch {
      /* storage unavailable: the URL still carries the view */
    }
  }, [sp, setSp]);
  const scored = board.runs.filter((r) => !r.dry_run && (r.scored ?? 0) > 0);
  const byId = new Map(scored.map((r) => [r.run_id, r]));
  const pick = (k: string) => {
    const v = sp.get(k);
    return v && byId.has(v) ? v : null;
  };
  const focus = pick('focus') ?? board.champion_run_id ?? scored[0]?.run_id ?? null;
  const challenger = pick('challenger');
  const group = (['dataset', 'style', 'query'] as const).find((g) => g === sp.get('group')) ?? 'dataset';
  const scope = sp.get('scope') === 'all' ? 'all' : 'common';
  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    setSp(next, { replace: true });
  };
  const q = focus ? `/api/runs/compare?focus=${focus}${challenger && challenger !== focus ? `&challenger=${challenger}` : ''}&group=${group}&scope=${scope}` : null;
  const { data: cmp, error } = useGet<CompareResp>(q);
  if (!focus) return <p className="empty">No scored run yet — nothing to compare.</p>;
  const label = (id: string) => {
    const r = byId.get(id);
    return r ? `${r.agent}@${r.fingerprint.slice(0, 7)} ${r.split}` : id;
  };
  const f = cmp?.sides[cmp.focus];
  const c = cmp?.challenger ? cmp.sides[cmp.challenger] : undefined;
  const fp = f?.profile;
  const cp = c?.profile;
  type Row = [string, (x: NonNullable<typeof f>) => string, number | null | undefined, number | null | undefined, 'pct' | 'usd' | 'int' | 'tok' | 'sec', boolean, number?];
  const rows: Row[] = f
    ? [
        ['macro Pass@1', (x) => fmtPct(x.pass_rate_macro), f.pass_rate_macro, c?.pass_rate_macro, 'pct', false],
        ['passed / scored (micro)', (x) => `${x.passed}/${x.scored} · ${fmtPct(x.pass_rate_micro)}`, f.pass_rate_micro, c?.pass_rate_micro, 'pct', false],
        ['cost per trial, p50', (x) => fmtUsd(x.profile.metrics.cost_usd.p50, 3), fp?.metrics.cost_usd.p50, cp?.metrics.cost_usd.p50, 'usd', true, 3],
        ['cost per trial, p95', (x) => fmtUsd(x.profile.metrics.cost_usd.p95, 3), fp?.metrics.cost_usd.p95, cp?.metrics.cost_usd.p95, 'usd', true, 3],
        ['cost per passed trial', (x) => fmtUsd(x.profile.cost_per_pass), fp?.cost_per_pass, cp?.cost_per_pass, 'usd', true, 2],
        ['turns, p50 / p95', (x) => `${x.profile.metrics.turns.p50} / ${x.profile.metrics.turns.p95}`, fp?.metrics.turns.p50, cp?.metrics.turns.p50, 'int', true],
        ['total tokens, p50 / p95', (x) => `${fmtTok(x.profile.metrics.total.p50)} / ${fmtTok(x.profile.metrics.total.p95)}`, fp?.metrics.total.p50, cp?.metrics.total.p50, 'tok', true],
        ['wall time, p50 / p95', (x) => `${fmtSec(x.profile.metrics.wall_s.p50)} / ${fmtSec(x.profile.metrics.wall_s.p95)}`, fp?.metrics.wall_s.p50, cp?.metrics.wall_s.p50, 'sec', true],
        ['timed out · errored', (x) => `${x.timeouts} · ${x.errors}`, f.timeouts, c?.timeouts, 'int', true],
        ['total cost', (x) => fmtUsd(x.cost_usd), f.cost_usd, c?.cost_usd, 'usd', true, 2],
      ]
    : [];
  return (
    <section className="band">
      <h2>
        01 · Compare —{' '}
        {cmp && f
          ? c
            ? `${label(cmp.focus)} ${fmtPct(f.pass_rate_macro)} against ${label(cmp.challenger ?? '')} ${fmtPct(c.pass_rate_macro)}${cmp.scope === 'common' ? ` on the ${cmp.common_queries} queries both scored` : ''}`
            : `${label(cmp.focus)} alone, ${fmtPct(f.pass_rate_macro)} macro; pick a challenger to compare`
          : 'loading'}
      </h2>
      <div className="filters">
        <label className="pick">
          <span className="label">focus</span>
          <select value={focus} onChange={(e) => set({ focus: e.target.value })} aria-label="focus run">
            {scored.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {runLabel(r)}
              </option>
            ))}
          </select>
        </label>
        <label className="pick">
          <span className="label">challenger</span>
          <select value={challenger ?? ''} onChange={(e) => set({ challenger: e.target.value || null })} aria-label="challenger run">
            <option value="">— none —</option>
            {scored
              .filter((r) => r.run_id !== focus)
              .map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {runLabel(r)}
                </option>
              ))}
          </select>
        </label>
        <label className="pick">
          <span className="label">group by</span>
          <select value={group} onChange={(e) => set({ group: e.target.value })} aria-label="group the figure by">
            <option value="dataset">dataset</option>
            <option value="style">validator style</option>
            <option value="query">query</option>
          </select>
        </label>
        {challenger && (
          <label className="pick">
            <span className="label">queries</span>
            <select value={scope} onChange={(e) => set({ scope: e.target.value === 'all' ? 'all' : null })} aria-label="which queries to compare on">
              <option value="common">only those both scored</option>
              <option value="all">each run's own</option>
            </select>
          </label>
        )}
      </div>
      {!cmp ? (
        <Loading error={error} />
      ) : (
        <>
          {c && cmp.scope === 'all' && cmp.scored_queries[cmp.focus] !== cmp.scored_queries[cmp.challenger ?? ''] && (
            <p className="small warn-note">
              Each run on its own queries: {cmp.scored_queries[cmp.focus]} against {cmp.scored_queries[cmp.challenger ?? '']}. The Δs compare different question sets and are indicative only — switch to "only those both scored" for a like-for-like number.
            </p>
          )}
          <div className="tw">
            <table>
              <thead>
                <tr>
                  <th>{cmp.scope === 'common' && c ? `On the ${cmp.common_queries} common queries` : 'On its own queries'}</th>
                  <th className="num">
                    <span className="sw a" /> focus
                    <span className="path">
                      <Link to={`/runs/${cmp.focus}`}>{label(cmp.focus)}</Link>
                    </span>
                  </th>
                  {c && (
                    <th className="num">
                      <span className="sw b" /> challenger
                      <span className="path">
                        <Link to={`/runs/${cmp.challenger}`}>{label(cmp.challenger ?? '')}</Link>
                      </span>
                    </th>
                  )}
                  {c && <th className="num">Δ challenger − focus</th>}
                </tr>
              </thead>
              <tbody>
                {rows.map(([name, show, fv, cv, fmt, lower, digits]) => (
                  <tr key={name}>
                    <td>{name}</td>
                    <td className="num">{f && show(f)}</td>
                    {c && <td className="num">{show(c)}</td>}
                    {c && (
                      <td className="num">
                        <Delta v={cv} base={fv} fmt={fmt} lowerIsBetter={lower} digits={digits ?? (fmt === 'pct' ? 1 : 0)} />
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {c && (cmp.fixed.length > 0 || cmp.broken.length > 0) && (
            <div className="chips">
              <span className="chip ok">fixed {cmp.fixed.length}</span>
              {cmp.fixed.map((qid) => (
                <Link key={qid} to={queryPath(qid)} className="chip ok">
                  {qid}
                </Link>
              ))}
              <span className="chip warn">broken {cmp.broken.length}</span>
              {cmp.broken.map((qid) => (
                <Link key={qid} to={queryPath(qid)} className="chip warn">
                  {qid}
                </Link>
              ))}
            </div>
          )}
          {c && cmp.fixed.length === 0 && cmp.broken.length === 0 && <p className="small muted">No query flips between the two: every query that passes in one passes in the other.</p>}
          <GroupBars cmp={cmp} base={base} label={label} />
          {f && <Ratios p={f.profile} />}
          {f && (
            <>
              <p className="label" style={{ marginTop: 'var(--s5)' }}>
                Per-trial distribution — {c ? `${label(cmp.challenger ?? '')}, with each Δ against the focus` : label(cmp.focus)}
              </p>
              {c ? <ProfileTable p={c.profile} versus={f.profile} versusLabel="focus" /> : <ProfileTable p={f.profile} />}
            </>
          )}
        </>
      )}
    </section>
  );
}

/** The board: who the champion is, what it costs to run, and every challenger measured against it. Nothing here is read from MLflow. */
export function Runs() {
  const { data: board, error } = useGet<Board>('/api/runs');
  const { data: lb } = useGet<Leaderboard>('/api/leaderboard');
  if (!board) return <Loading error={error} />;
  const runs = board.runs;
  const champ = runs.find((r) => r.run_id === board.champion_run_id) ?? null;
  const challengers = runs.filter((r) => r.role === 'challenger' || r.role === 'superseded');
  const live = runs.filter((r) => !r.dry_run && r.scored);
  const spent = live.reduce((s, r) => s + (r.cost_usd ?? 0), 0);
  const trials = live.reduce((s, r) => s + (r.n ?? 0), 0);
  const base = bestBaseline(lb);
  const cp = champ?.profile;
  return (
    <>
      <p className="label">
        runs · {runs.length} folder{runs.length === 1 ? '' : 's'} on this machine · champion pointer <code>agents/champion → {board.champion}</code>
      </p>
      <h1>
        {champ ? (
          <>
            The champion is {champ.agent}@{champ.fingerprint}: macro Pass@1 {fmtPct(champ.pass_rate_macro)} on {champ.n_queries} × {champ.trials} ({champ.passed}/{champ.scored}),{' '}
            {fmtUsd(cp?.metrics.cost_usd.p50, 2)} a trial at the median — <em>{challengers.length === 0 ? 'no challenger has run yet' : `${challengers.length} challenger${challengers.length === 1 ? '' : 's'} measured against it`}</em>
          </>
        ) : (
          <>
            No champion yet: a champion is the newest scored run of <code>{board.champion}</code> on the <em>full</em> split
          </>
        )}
      </h1>
      <p className="lead">
        A run is a folder under <code>runs/</code>; its role is derived, not declared. The newest scored full-split run of the agent <code>agents/champion</code> names is the champion; every other full-split run is a challenger (or a superseded champion);
        a smoke run screens one query per dataset and never holds the title. The same runs are logged to the central MLflow (<code>dataagentbench/evals</code>) and linked from each page.
      </p>

      <Compare board={board} base={base} />

      <h2>
        02 · Challengers — {challengers.length === 0 ? 'none has run; the first is the DAB addendum at 54 × 5' : `${challengers.length} measured against the champion on the same 54`}
      </h2>
      {challengers.length === 0 ? (
        <p className="empty">
          A challenger is any full-split run that is not the champion: <code>dab eval --agent &lt;name&gt; --split all --trials 5 --challenger_of {champ?.run_id ?? '<champion run>'}</code>. Its row here shows every Δ against the champion; <code>dab promote</code> moves the pointer.
        </p>
      ) : (
        <div className="tw">
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Role</th>
                <th>Agent</th>
                <th className="num">Macro</th>
                <th className="num">Δ macro</th>
                <th>Pass (micro)</th>
                <th className="num">Cost p50</th>
                <th className="num">Δ</th>
                <th className="num">Turns p50 / p95</th>
                <th className="num">Δ p50</th>
                <th className="num">Tokens p50</th>
                <th className="num">Timeouts</th>
              </tr>
            </thead>
            <tbody>
              {challengers.map((r) => (
                <tr key={r.run_id}>
                  <td className="sub">
                    <Link to={`/runs/${r.run_id}`} className="mono">
                      {r.run_id}
                    </Link>
                    <span className="path">
                      {r.started_at.slice(0, 16).replace('T', ' ')} · {r.n_queries} × {r.trials} · {r.model.replace('claude-', '')} @ {r.effort}
                      {r.challenger_of ? ` · challenger of ${r.challenger_of.slice(0, 16)}` : ''}
                    </span>
                  </td>
                  <td>
                    <Role role={r.role} />
                  </td>
                  <td className="mono">
                    {r.agent}@{r.fingerprint}
                  </td>
                  <td className="num">{fmtPct(r.pass_rate_macro)}</td>
                  <td className="num">
                    <Delta v={r.pass_rate_macro} base={champ?.pass_rate_macro} fmt="pct" />
                  </td>
                  <td>
                    <Rate passed={r.passed} n={r.scored} />
                  </td>
                  <td className="num">{fmtUsd(r.profile.metrics.cost_usd.p50, 3)}</td>
                  <td className="num">
                    <Delta v={r.profile.metrics.cost_usd.p50} base={cp?.metrics.cost_usd.p50} fmt="usd" lowerIsBetter digits={3} />
                  </td>
                  <td className="num">
                    {r.profile.metrics.turns.p50} / {r.profile.metrics.turns.p95}
                  </td>
                  <td className="num">
                    <Delta v={r.profile.metrics.turns.p50} base={cp?.metrics.turns.p50} fmt="int" lowerIsBetter />
                  </td>
                  <td className="num">{fmtTok(r.profile.metrics.total.p50)}</td>
                  <td className="num">{r.timeouts ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2>
        03 · Every run — {live.length} scored, {trials} trials, {fmtUsd(spent)} on the subscription
      </h2>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>Run</th>
              <th>Role</th>
              <th>Agent</th>
              <th>Pass (micro)</th>
              <th className="num">Macro</th>
              <th className="num">Turns p50 / p95</th>
              <th className="num">Tokens p50 / p95</th>
              <th className="num">Cost p50 / p95</th>
              <th className="num">Total</th>
              <th className="num">Wall</th>
              <th className="num">Timeouts</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.run_id} className={r.role === 'dry' || r.role === 'superseded' ? 'dim' : r.role === 'champion' ? 'pro' : ''}>
                <td className="sub">
                  <Link to={`/runs/${r.run_id}`} className="mono">
                    {r.run_id}
                  </Link>
                  <span className="path">
                    {r.started_at.slice(0, 16).replace('T', ' ')} · {r.split} · {r.n_queries} × {r.trials} · {r.model.replace('claude-', '')} @ {r.effort} · {r.hints ? 'hints on' : 'no hints'}
                  </span>
                </td>
                <td>
                  <Role role={r.role} />
                </td>
                <td className="mono">
                  {r.agent}@{r.fingerprint}
                </td>
                <td>{r.dry_run ? <span className="muted">dry run</span> : <Rate passed={r.passed} n={r.scored} />}</td>
                <td className="num">{r.dry_run ? '—' : fmtPct(r.pass_rate_macro)}</td>
                <td className="num">
                  {r.profile.metrics.turns.p50} / {r.profile.metrics.turns.p95}
                </td>
                <td className="num">
                  {fmtTok(r.profile.metrics.total.p50)} / {fmtTok(r.profile.metrics.total.p95)}
                </td>
                <td className="num">
                  {fmtUsd(r.profile.metrics.cost_usd.p50, 2)} / {fmtUsd(r.profile.metrics.cost_usd.p95, 2)}
                </td>
                <td className="num">{fmtUsd(r.cost_usd)}</td>
                <td className="num">{fmtDur(r.duration_ms)}</td>
                <td className="num">{r.timeouts ?? 0}</td>
                <td className="wrap-any small">{r.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {runs.length === 0 && <p className="empty">No runs yet. `make eval` writes the first one; a dry run (`dab eval --dry-run --no-mlflow`) needs no model.</p>}
    </>
  );
}
