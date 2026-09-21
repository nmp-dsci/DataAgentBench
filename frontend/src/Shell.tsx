import { NavLink, Outlet } from 'react-router-dom';
import { type Health, shortSha, useGet } from './lib/api';

const NAV: [string, string][] = [
  ['/', 'Overview'],
  ['/datasets', 'Datasets'],
  ['/queries', 'Queries'],
  ['/validators', 'Validators'],
  ['/leaderboard', 'Leaderboard'],
  ['/runs', 'Runs'],
];

export function Shell() {
  const { data: health } = useGet<Health>('/healthz');
  return (
    <>
      <header className="top">
        <div className="in">
          <NavLink to="/" className="brand">
            <img src="/favicon.svg" alt="" width="22" height="22" />
            <span>
              DAB<b> explorer</b>
            </span>
          </NavLink>
          <nav aria-label="Pages">
            {NAV.map(([to, label]) => (
              <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => (isActive ? 'on' : '')}>
                {label}
              </NavLink>
            ))}
          </nav>
          <span className={`mode ${health?.rescored ? 'ok' : ''}`} title="whether data/index/trials.json is present">
            {health ? (health.rescored ? 'rescored' : 'not rescored') : '…'}
          </span>
        </div>
      </header>
      <main>
        <Outlet context={health} />
      </main>
      <footer>
        Every number on these pages is read from a committed file: <code>data/index/</code> and <code>data/answers/</code>, built from{' '}
        <a href="https://github.com/ucbepic/DataAgentBench">ucbepic/DataAgentBench</a> at <code>{shortSha(health?.source.commit)}</code>. Attribution in{' '}
        <code>data/index/ATTRIBUTION.md</code>. <a href="https://github.com/nmp-dsci/DataAgentBench">Source</a>.
      </footer>
    </>
  );
}
