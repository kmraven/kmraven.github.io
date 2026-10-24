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

test('private fields and drafts stay hidden while manual profile content renders', { timeout: 60000 }, async () => {
  // macOS aliases /var to /private/var; Vite's virtual module IDs need one real path.
  const temporary = await realpath(await mkdtemp(path.join(tmpdir(), 'portal-privacy-')));
  try {
    await cp(path.join(root, 'src'), path.join(temporary, 'src'), { recursive: true });
    await cp(path.join(root, 'content'), path.join(temporary, 'content'), { recursive: true });
    await cp(path.join(root, 'public'), path.join(temporary, 'public'), { recursive: true });
    await cp(path.join(root, 'astro.config.mjs'), path.join(temporary, 'astro.config.mjs'));
    await cp(path.join(root, 'package.json'), path.join(temporary, 'package.json'));
    await cp(path.join(root, 'tsconfig.json'), path.join(temporary, 'tsconfig.json'));
    await symlink(path.join(root, 'node_modules'), path.join(temporary, 'node_modules'), 'dir');
    const input = snapshot(
      record('education', 2, { display: 'closed', affiliation: { ja: 'PRIVATE_TEST_SCHOOL', en: 'PRIVATE_TEST_SCHOOL' }, from_date: '2010-04' }),
      record('education', 3, { display: 'disclosed', affiliation: { en: 'Public Example University' }, from_date: '2026-04', to_date: '9999' }),
      record('education', 6, { display: 'disclosed', affiliation: { en: 'Public Example University' }, from_date: '2020-04', to_date: '2024-03' }),
      record('published_papers', 4, examplePaper),
      record('presentations', 5, { display: 'researchers_only', presentation_title: { en: 'PRIVATE_TEST_TALK' } }),
    );
    const { data } = importResearchmap(input);
    await writeFile(path.join(temporary, 'src/data/researchmap.public.json'), JSON.stringify(data));
    await writeFile(path.join(temporary, 'content/profile.md'), `---
current_lab: "current"
links:
  github: "https://github.com/example"
  x: "https://x.com/example"
  linkedin: "https://www.linkedin.com/in/example/"
  google_scholar: ""
---
PROFILE_INSTRUCTIONS_NOT_FOR_SITE
`);
    await writeFile(path.join(temporary, 'content/history.md'), `---
entries:
  - id: current
    category: education
    match: { organization: "Public Example University", start: "2026-04" }
    lab:
      name: { ja: "公開テスト研究室", en: "Public Example Lab" }
      url: "https://example.org/lab"
  - id: previous
    category: education
    match: { organization: "Public Example University", start: "2020-04" }
    lab:
      name: { ja: "", en: "Previous Example Lab" }
      url: ""
  - id: hidden
    category: education
    match: { organization: "PRIVATE_TEST_SCHOOL", start: "2010-04" }
    lab:
      name: { ja: "PRIVATE_TEST_LAB", en: "PRIVATE_TEST_LAB" }
      url: "https://example.org/PRIVATE_TEST_LAB"
---
`);
    await writeFile(path.join(temporary, 'content/education.md'), `---
entries:
  - organization: { en: "Public Example University" }
    start: "2026-04"
    end: null
  - organization: { ja: "手動テスト学校", en: "Manual Example School" }
    start: "2013-04"
    end: "2016-03"
---
EDUCATION_INSTRUCTIONS_NOT_FOR_SITE
`);
    await writeFile(path.join(temporary, 'content/about/ja.md'), '---\npublished: true\n---\n公開テスト自己紹介');
    await writeFile(path.join(temporary, 'content/about/en.md'), '---\npublished: false\n---\nDRAFT_TEST_BIO');
    const cli = await realpath(path.join(root, 'node_modules/.bin/astro'));
    const build = spawnSync(process.execPath, [cli, 'build', '--root', temporary], {
      cwd: temporary, encoding: 'utf8', timeout: 45000,
      env: { ...process.env, ASTRO_TELEMETRY_DISABLED: '1' },
    });
    assert.equal(build.status, 0, `${build.stdout}\n${build.stderr}`);
    for (const page of ['index.html', 'cv/index.html', 'en/index.html', 'en/cv/index.html']) {
      const html = await readFile(path.join(temporary, 'dist', page), 'utf8');
      assert(!html.includes('PRIVATE_TEST'), `Private information leaked into ${page}`);
      assert(!html.includes('user_id'));
      assert(!html.includes('DRAFT_TEST_BIO'), `Draft biography leaked into ${page}`);
      assert(!html.includes('PROFILE_INSTRUCTIONS_NOT_FOR_SITE'));
      assert(!html.includes('EDUCATION_INSTRUCTIONS_NOT_FOR_SITE'));
      const manualName = page.startsWith('en/') ? 'Manual Example School' : '手動テスト学校';
      assert.equal(html.includes(manualName), page.endsWith('cv/index.html'));
      if (page.endsWith('cv/index.html')) {
        assert.equal((html.match(/data-record="manual-education"/g) ?? []).length, 1);
        assert.equal((html.match(/data-record="education"/g) ?? []).length, 2);
      }
      assert(!html.includes('Google Scholar'), `Empty profile link rendered in ${page}`);
      {
        assert(html.includes(page.startsWith('en/') ? 'Public Example Lab' : '公開テスト研究室'));
        for (const url of ['https://example.org/lab', 'https://x.com/example', 'https://www.linkedin.com/in/example/']) {
          assert(html.includes(`href="${url}"`), `Missing manual link in ${page}: ${url}`);
        }
      }
      assert.equal(html.includes('公開テスト自己紹介'), page === 'index.html');
      assert.equal(html.includes('Previous Example Lab'), page.endsWith('cv/index.html'));
    }
    const cv = await readFile(path.join(temporary, 'dist/cv/index.html'), 'utf8');
    assert(cv.includes('Public Example University'));
    assert(cv.includes('An example preprint'));
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});
