import { type LoaderFunctionArgs, type RouteObject, redirect } from 'react-router-dom';
import { Shell } from './Shell';
import { Agent, AGENT_VIEW } from './pages/Agent';
import { Dataset } from './pages/Dataset';
import { Datasets } from './pages/Datasets';
import { Golden, GoldenEditor } from './pages/Golden';
import { Leaderboard } from './pages/Leaderboard';
import { Overview } from './pages/Overview';
import { Query } from './pages/Query';
import { Run } from './pages/Run';
import { Runs } from './pages/Runs';
import { TracePage } from './pages/TracePage';
import { Validators } from './pages/Validators';
import { agentPath, questionPath, runPath, search, trialIdFromStem, trialPath } from './lib/url';

/**
 * Every explorer address, as data (`tests/routes.test.ts` drives it in a memory router).
 * The grammar is in `lib/url.ts`. Old addresses are redirect loaders, never 404s: a
 * bookmark, a review note or a README link from before keeps landing.
 */

/** The Agent tab's pre-grammar lens: `?agent=<v>` in the query string and `trial=<file stem>`. */
function agentLegacy(url: URL, version: string | null): string | null {
  const sp = url.searchParams;
  const stem = sp.get('trial');
  const trial = stem && !stem.includes('/') ? trialIdFromStem(stem) : null;
  if (!sp.has('agent') && !trial) return null;
  const lens = Object.fromEntries(sp.entries());
  delete lens.agent;
  if (trial) lens.trial = trial;
  return agentPath(version ?? sp.get('agent') ?? 'champion', lens);
}

export const routes: RouteObject[] = [
  {
    id: 'shell',
    element: <Shell />,
    hydrateFallbackElement: <></>,
    children: [
      { id: 'overview', path: '/', element: <Overview /> },
      { id: 'datasets', path: '/datasets', element: <Datasets /> },
      { id: 'dataset', path: '/datasets/:key', element: <Dataset /> },
      { id: 'question', path: '/datasets/:key/:n', element: <Query /> },
      { id: 'validators', path: '/validators', element: <Validators /> },
      { id: 'leaderboard', path: '/leaderboard', element: <Leaderboard /> },
      { id: 'runs', path: '/runs', element: <Runs /> },
      { id: 'run', path: '/runs/:id', element: <Run /> },
      // the two middle chops of a trial address land on the run, narrowed to that dataset or question
      { id: 'run-dataset', path: '/runs/:id/:ds', loader: ({ params }) => redirect(runPath(params.id!, { q: params.ds })) },
      { id: 'run-question', path: '/runs/:id/:ds/:n', loader: ({ params }) => redirect(runPath(params.id!, { q: `${params.ds}/${params.n}` })) },
      { id: 'trial', path: '/runs/:id/:ds/:n/:t', element: <TracePage /> },
      {
        id: 'agent-bare',
        path: '/agent',
        loader: ({ request }: LoaderFunctionArgs) => {
          const legacy = agentLegacy(new URL(request.url), null);
          if (legacy) return redirect(legacy);
          // the nav's bare /agent comes back to the last view in this browser tab
          try {
            const last = sessionStorage.getItem(AGENT_VIEW);
            if (last?.startsWith('/agent/')) return redirect(last);
          } catch {
            /* storage unavailable: the default view */
          }
          return redirect(agentPath('champion'));
        },
      },
      {
        id: 'agent',
        path: '/agent/:version',
        element: <Agent />,
        loader: ({ request, params }: LoaderFunctionArgs) => {
          const legacy = agentLegacy(new URL(request.url), params.version!);
          return legacy ? redirect(legacy) : null;
        },
      },
      {
        id: 'golden',
        path: '/golden',
        element: <Golden />,
        // rule 3: the editor opens inside the list page, which stays mounted
        children: [{ id: 'golden-editor', path: ':key/:n', element: <GoldenEditor /> }],
      },

      // ── addresses from before the grammar ──
      { id: 'old-queries', path: '/queries', loader: () => redirect('/datasets') },
      { id: 'old-question', path: '/queries/:key/:n', loader: ({ params }) => redirect(questionPath(`${params.key}/${params.n}`)) },
      {
        id: 'old-trace',
        path: '/runs/:id/traces/:key',
        loader: ({ params, request }) => {
          const tid = trialIdFromStem(params.key!);
          const q = Object.fromEntries(new URL(request.url).searchParams.entries());
          return redirect(tid ? `${trialPath(params.id!, tid)}${search(q)}` : runPath(params.id!));
        },
      },
    ],
  },
];
