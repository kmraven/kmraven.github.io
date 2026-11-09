import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtemp, mkdir, writeFile, rm, utimes } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { aboutDate, readAboutRevisions } from '../src/lib/about-history.ts';

const markdown = (body: string, published = true) => `---\npublished: ${published}\n---\n\n${body}\n`;
async function repository() {
  const root = await mkdtemp(path.join(tmpdir(), 'portal-about-'));
  await mkdir(path.join(root, 'content/about'), { recursive: true });
  const git = (args: string[], date = '2026-10-24T10:00:00+09:00') => execFileSync('git', args, {
    cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, GIT_AUTHOR_NAME: 'Fixture', GIT_COMMITTER_NAME: 'Fixture',
      GIT_AUTHOR_EMAIL: 'fixture@example.org', GIT_COMMITTER_EMAIL: 'fixture@example.org',
      GIT_AUTHOR_DATE: date, GIT_COMMITTER_DATE: date },
  });
  git(['init']);
  async function commit(lang: 'ja' | 'en', body: string, date: string, published = true) {
    await writeFile(path.join(root, `content/about/${lang}.md`), markdown(body, published));
    git(['add', `content/about/${lang}.md`]);
    git(['-c', 'commit.gpgsign=false', 'commit', '-m', 'Update biography'], date);
  }
  return { root, commit, clean: () => rm(root, { recursive: true, force: true }) };
}

test('biography dates come from each file, unaffected by checkout time or unrelated commits', async () => {
  const repo = await repository();
  try {
    await repo.commit('ja', '日本語', '2026-10-24T16:30:00Z'); // Oct 25 in Japan.
    await repo.commit('en', 'English', '2026-10-26T10:00:00+09:00');
    await utimes(path.join(repo.root, 'content/about/ja.md'), new Date(), new Date());
    assert.equal((await readAboutRevisions(repo.root, 'ja'))[0].date, '2026-10-25');
    assert.equal((await readAboutRevisions(repo.root, 'en'))[0].date, '2026-10-26');
    assert.equal(aboutDate('2026-10-24T16:30:00Z'), '2026-10-25');
  } finally { await repo.clean(); }
});

test('one latest version per day, with private snapshots and private current content excluded', async () => {
  const repo = await repository();
  try {
    await repo.commit('ja', 'Initial', '2026-10-24T10:00:00+09:00');
    await repo.commit('ja', 'DRAFT_TEST_BIO', '2026-10-25T10:00:00+09:00', false);
    await repo.commit('ja', 'Morning', '2026-10-26T10:00:00+09:00');
    await repo.commit('ja', 'Evening **Markdown**', '2026-10-26T20:00:00+09:00');
    const versions = await readAboutRevisions(repo.root, 'ja');
    assert.deepEqual(versions.map(v => v.date), ['2026-10-26']);
    assert(!JSON.stringify(versions).includes('Initial'));
    assert(versions[0].body.includes('**Markdown**'));
    assert(!JSON.stringify(versions).includes('DRAFT_TEST_BIO'));
    await writeFile(path.join(repo.root, 'content/about/ja.md'), markdown('Hidden now', false));
    assert.deepEqual(await readAboutRevisions(repo.root, 'ja'), []);
    await rm(path.join(repo.root, 'content/about/ja.md'));
    assert.deepEqual(await readAboutRevisions(repo.root, 'ja'), []);
  } finally { await repo.clean(); }
});

test('uncommitted changes use filesystem date and replace the same day, without requiring Git for source-only previews', async () => {
  const repo = await repository();
  try {
    await repo.commit('ja', 'Committed', '2026-10-24T10:00:00+09:00');
    const file = path.join(repo.root, 'content/about/ja.md');
    await writeFile(file, markdown('Local preview'));
    const date = new Date('2026-10-25T12:00:00+09:00');
    await utimes(file, date, date);
    assert.deepEqual((await readAboutRevisions(repo.root, 'ja')).map(v => v.date), ['2026-10-25']);
    await rm(path.join(repo.root, '.git'), { recursive: true, force: true });
    assert.deepEqual((await readAboutRevisions(repo.root, 'ja')).map(v => v.date), ['2026-10-25']);
    await writeFile(file, markdown('<!-- nothing public -->'));
    assert.deepEqual(await readAboutRevisions(repo.root, 'ja'), []);
  } finally { await repo.clean(); }
});
