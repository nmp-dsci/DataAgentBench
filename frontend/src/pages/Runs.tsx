import { Link } from 'react-router-dom';
import { type Board, type Leaderboard, type RunSummary, fmtDur, fmtPct, fmtSec, fmtTok, fmtUsd, useGet } from '../lib/api';
import { Delta, ProfileTable, Ratios, Role } from '../lib/runs';
import { Kpi, Loading, Rate } from '../lib/ui';

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

/** Champion rate per dataset against the best plain baseline: where the pack helps and where it does not. */
function DatasetBars({ run, base }: { run: RunSummary; base: ReturnType<typeof bestBaseline> }) {
  const ds = Object.entries(run.per_dataset ?? {}).sort(([a], [b]) => a.localeCompare(b));
  if (!ds.length) return null;
  const W = 1000;
  const rowH = 30;
  const top = 26;
  const H = top + ds.length * rowH + 8;
  const labelW = 190;
  const trackW = W - labelW - 70;
  return (
    <figure>
      <p className="label">Fig · the champion per dataset, against {base ? `the ${base.label} baseline` : 'nothing yet'}</p>
      <svg className="dia" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Pass rate per dataset for the champion run, with the best plain baseline as a marker">
        <title>Champion pass rate per dataset</title>
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <g key={f}>
            <line className="ax" x1={labelW + f * trackW} x2={labelW + f * trackW} y1={top - 6} y2={H - 8} />
            <text className="tx k" x={labelW + f * trackW} y={top - 10} textAnchor="middle">
              {f * 100}%
            </text>
          </g>
        ))}
        {ds.map(([name, v], i) => {
          const y = top + i * rowH;
          const r = v.rate ?? 0;
          const b = base?.perDataset[name];
          return (
            <g key={name} id={`ds-${name}`}>
              <title>
                {name}: {v.passed}/{v.n} passed ({fmtPct(r)}){b != null ? `, baseline ${fmtPct(b)}` : ''}
              </title>
              <text className="tx" x={labelW - 10} y={y + 19} textAnchor="end">
                {name}
              </text>
              <rect className="bar" x={labelW} y={y + 6} width={trackW} height={16} opacity={0.35} />
              <rect className={r > 0 ? 'bar hi' : 'bar pro'} x={labelW} y={y + 6} width={Math.max(2, r * trackW)} height={16} />
              {b != null && <line className="ax mark" x1={labelW + b * trackW} x2={labelW + b * trackW} y1={y + 2} y2={y + 26} />}
              <text className="tx k" x={labelW + trackW + 8} y={y + 19}>
                {v.passed}/{v.n}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption>
        Bars are the champion's pass rate per dataset (passed/trials at the right); the dark tick is {base ? `${base.label}, the best plain-ReAct baseline on the leaderboard (${fmtPct(base.overall)} overall)` : 'absent until the leaderboard loads'}. Source:{' '}
        <code>runs/{run.run_id}/run.json</code>, <code>data/index/leaderboard.json</code>.
      </figcaption>
    </figure>
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
  const top = lb?.overallLeaderboard[0];
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

      {champ && cp && (
        <section className="band">
          <h2>
            01 · Champion — {fmtPct(champ.pass_rate_macro)} macro against {base ? `${fmtPct(base.overall)} for ${base.label}` : 'the leaderboard'}
            {top ? ` and ${fmtPct(top.passAt1)} at the top` : ''}
          </h2>
          <p>
            <Link to={`/runs/${champ.run_id}`} className="mono">
              {champ.run_id}
            </Link>{' '}
            · <code>{champ.model.replace('claude-', '')}</code> at effort <code>{champ.effort}</code> · hints {champ.hints ? 'on' : 'off'} · context <code>{champ.context_sha}</code> · {fmtDur(champ.duration_ms)} of trial time summed, {fmtUsd(champ.cost_usd)} total.{champ.mlflow_url && (
              <>
                {' '}
                <a href={champ.mlflow_url}>MLflow run</a>.
              </>
            )}
          </p>
          <div className="kpis">
            <Kpi n={`${fmtPct(champ.pass_rate_macro)} · ${champ.passed}/${champ.scored}`} b={`macro Pass@1 · micro pass, ${champ.n_queries} queries × ${champ.trials}`} tone="ok" />
            <Kpi n={`${fmtUsd(cp.metrics.cost_usd.p50, 2)} / ${fmtUsd(cp.metrics.cost_usd.p95, 2)}`} b="cost per trial, p50 / p95 (Agent SDK cost_usd)" />
            <Kpi n={`${cp.metrics.turns.p50} / ${cp.metrics.turns.p95}`} b="turns per trial, p50 / p95" />
            <Kpi n={`${fmtSec(cp.metrics.wall_s.p50)} / ${fmtSec(cp.metrics.wall_s.p95)}`} b="wall time per trial, p50 / p95" />
            <Kpi n={`${fmtTok(cp.metrics.total.p50)} / ${fmtTok(cp.metrics.total.p95)}`} b="total tokens per trial, p50 / p95" />
            <Kpi n={fmtUsd(cp.cost_per_pass)} b="cost per passed trial" tone={cp.cost_per_pass != null && cp.cost_per_trial != null && cp.cost_per_pass > 2 * cp.cost_per_trial ? 'warn' : undefined} />
          </div>
          <Ratios p={cp} />
          <DatasetBars run={champ} base={base} />
          <ProfileTable p={cp} />
        </section>
      )}

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
