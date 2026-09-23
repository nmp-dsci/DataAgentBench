/**
 * The URL grammar, enforced: every address the explorer ever published still lands, and
 * every address it builds matches the page it names. Drives the real route table in a
 * memory router (loaders and redirects run; nothing renders), plus the id helpers.
 */
import { createMemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { patchLens, search, trialId, trialIdFromStem, parseTrialId, questionPath, trialPath, agentPath } from './lib/url';
import { routes } from './routes';

const RUN = '20260921T064521Z_v0_all_haiku';
// every dataset key in scope: underscores and trailing digits are what make the old stem hard to split
const DATASETS = ['agnews', 'bookreview', 'crmarenapro', 'deps_dev_v1', 'github_repos', 'googlelocal', 'music_brainz_20k', 'pancancer_atlas', 'patents', 'stockindex', 'stockmarket', 'yelp'];

async function land(url: string): Promise<{ path: string; route: string | undefined }> {
  const router = createMemoryRouter(routes, { initialEntries: [url] });
  await new Promise<void>((resolve) => {
    if (router.state.initialized && router.state.navigation.state === 'idle') return resolve();
    const off = router.subscribe((s) => {
      if (s.initialized && s.navigation.state === 'idle') {
        off();
        resolve();
      }
    });
  });
  const { pathname, search: qs } = router.state.location;
  const route = router.state.matches.at(-1)?.route.id;
  router.dispose();
  return { path: decodeURIComponent(`${pathname}${qs}`), route };
}

describe('old addresses redirect to the new ones', () => {
  it.each([
    ['/queries', '/datasets', 'datasets'],
    ['/queries/deps_dev_v1/1', '/datasets/deps_dev_v1/1', 'question'],
    [`/runs/${RUN}/traces/deps_dev_v1_1_t1`, `/runs/${RUN}/deps_dev_v1/1/t1`, 'trial'],
    [`/runs/${RUN}/traces/pancancer_atlas_2_t1`, `/runs/${RUN}/pancancer_atlas/2/t1`, 'trial'],
    [`/runs/${RUN}/traces/not-a-trial`, `/runs/${RUN}`, 'run'],
    ['/agent', '/agent/champion', 'agent'],
    [
      `/agent?agent=v0&run=${RUN}&trial=pancancer_atlas_2_t1&node=tool%3Aexecute_python`,
      `/agent/v0?run=${RUN}&trial=pancancer_atlas/2/t1&node=tool:execute_python`,
      'agent',
    ],
    [`/agent/champion?run=${RUN}&trial=yelp_1_t3`, `/agent/champion?run=${RUN}&trial=yelp/1/t3`, 'agent'],
    [`/runs/${RUN}/deps_dev_v1`, `/runs/${RUN}?q=deps_dev_v1`, 'run'],
    [`/runs/${RUN}/deps_dev_v1/1`, `/runs/${RUN}?q=deps_dev_v1/1`, 'run'],
  ])('%s → %s', async (from, to, route) => {
    const got = await land(from);
    expect(got.path).toBe(to);
    expect(got.route).toBe(route);
  });

  it.each(DATASETS)('an old trace address for %s splits back into its id', async (ds) => {
    const got = await land(`/runs/${RUN}/traces/${ds}_12_t3`);
    expect(got.path).toBe(`/runs/${RUN}/${ds}/12/t3`);
  });
});

describe('every address the explorer builds lands on the page it names', () => {
  it.each([
    ['/', 'overview'],
    ['/datasets', 'datasets'],
    ['/datasets/deps_dev_v1', 'dataset'],
    [questionPath('deps_dev_v1/1'), 'question'],
    ['/validators', 'validators'],
    ['/leaderboard', 'leaderboard'],
    ['/runs?focus=a&challenger=lb:permute_eq', 'runs'],
    [`/runs/${RUN}`, 'run'],
    [trialPath(RUN, 'deps_dev_v1/1/t1'), 'trial'],
    [agentPath('champion', { run: RUN, trial: 'yelp/1/t1', node: 'tool:query_db' }), 'agent'],
    ['/golden', 'golden'],
    ['/golden/deps_dev_v1/1', 'golden-editor'],
  ])('%s', async (url, route) => {
    const got = await land(url);
    expect(got.route).toBe(route);
    expect(got.path).toBe(decodeURIComponent(url));
  });

  it('the golden editor is nested in the list, so the list stays mounted', async () => {
    const router = createMemoryRouter(routes, { initialEntries: ['/golden/deps_dev_v1/1'] });
    expect(router.state.matches.map((m) => m.route.id)).toEqual(['shell', 'golden', 'golden-editor']);
    router.dispose();
  });
});

describe('ids and the lens', () => {
  it('a trial id is the question id plus /t<k>, and parses back', () => {
    expect(trialId({ query_id: 'deps_dev_v1/1', trial: 1 })).toBe('deps_dev_v1/1/t1');
    expect(parseTrialId('deps_dev_v1/1/t1')).toEqual({ queryId: 'deps_dev_v1/1', dataset: 'deps_dev_v1', n: 1, trial: 1 });
    expect(parseTrialId('deps_dev_v1_1_t1')).toBeNull();
  });

  it('the old file stem converts to the id, and nothing else does', () => {
    expect(trialIdFromStem('music_brainz_20k_3_t2')).toBe('music_brainz_20k/3/t2');
    expect(trialIdFromStem('deps_dev_v1')).toBeNull();
  });

  it('the lens keeps / : and , readable and escapes the rest', () => {
    expect(search({ trial: 'yelp/1/t1', node: 'tool:query_db', ids: 'a,b' })).toBe('?trial=yelp/1/t1&node=tool:query_db&ids=a,b');
    expect(search({ note: 'a&b=c #1 50%' })).toBe('?note=a%26b%3Dc%20%231%2050%25');
    expect(search({ a: '', b: null })).toBe('');
    expect(patchLens(new URLSearchParams('focus=x&challenger=lb%3Apermute_eq'), { focus: null, group: 'style' })).toBe('?challenger=lb:permute_eq&group=style');
  });
});

describe('the golden editor starts from the SQL behind the answer', () => {
  const call = (output: string, error = false) => ({ output, error });
  it('prefers the last call whose output holds the answer over a later check', async () => {
    const { seedCall } = await import('./pages/Golden');
    const calls = [call('state\tn\nPA\t1000'), call('avg\n3.7648'), call('count\n42')];
    expect(seedCall(calls, 'Pennsylvania; 3.76')).toBe(calls[1]);
  });
  it('falls back to the last error-free call, and skips errors', async () => {
    const { seedCall } = await import('./pages/Golden');
    const calls = [call('a\n1'), call('b\n2'), call('ERROR', true)];
    expect(seedCall(calls, 'nothing matches')).toBe(calls[1]);
    expect(seedCall([], 'x')).toBeNull();
  });
});
