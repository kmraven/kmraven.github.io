import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, cp, writeFile, readFile, symlink, rm, realpath } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { importResearchmap } from '../src/lib/import-researchmap.ts';
import { record, snapshot, examplePaper } from './fixtures.ts';

const root = fileURLToPath(new URL('../', import.meta.url));

test('private fields remain absent from all six rendered HTML pages', { timeout: 60000 }, async () => {
  // macOS aliases /var to /private/var; Vite's virtual module IDs need one real path.
  const temporary = await realpath(await mkdtemp(path.join(tmpdir(), 'portal-privacy-')));
  try {
    await cp(path.join(root, 'src'), path.join(temporary, 'src'), { recursive: true });
    await cp(path.join(root, 'public'), path.join(temporary, 'public'), { recursive: true });
    await cp(path.join(root, 'astro.config.mjs'), path.join(temporary, 'astro.config.mjs'));
    await cp(path.join(root, 'package.json'), path.join(temporary, 'package.json'));
    await cp(path.join(root, 'tsconfig.json'), path.join(temporary, 'tsconfig.json'));
    await symlink(path.join(root, 'node_modules'), path.join(temporary, 'node_modules'), 'dir');
    const input = snapshot(
      record('education', 2, { display: 'closed', affiliation: { ja: 'PRIVATE_TEST_SCHOOL', en: 'PRIVATE_TEST_SCHOOL' } }),
      record('education', 3, { display: 'disclosed', affiliation: { en: 'Public Example University' }, from_date: '2026-04', to_date: '9999' }),
      record('published_papers', 4, examplePaper),
      record('presentations', 5, { display: 'researchers_only', presentation_title: { en: 'PRIVATE_TEST_TALK' } }),
    );
    const { data } = importResearchmap(input);
    await writeFile(path.join(temporary, 'src/data/researchmap.public.json'), JSON.stringify(data));
    const cli = await realpath(path.join(root, 'node_modules/.bin/astro'));
    const build = spawnSync(process.execPath, [cli, 'build', '--root', temporary], {
      cwd: temporary, encoding: 'utf8', timeout: 45000,
      env: { ...process.env, ASTRO_TELEMETRY_DISABLED: '1' },
    });
    assert.equal(build.status, 0, `${build.stdout}\n${build.stderr}`);
    for (const page of ['index.html', 'publications/index.html', 'cv/index.html', 'en/index.html', 'en/publications/index.html', 'en/cv/index.html']) {
      const html = await readFile(path.join(temporary, 'dist', page), 'utf8');
      assert(!html.includes('PRIVATE_TEST'), `Private information leaked into ${page}`);
      assert(!html.includes('user_id'));
    }
    const cv = await readFile(path.join(temporary, 'dist/cv/index.html'), 'utf8');
    assert(cv.includes('Public Example University'));
    assert(cv.includes('An example preprint'));
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});
