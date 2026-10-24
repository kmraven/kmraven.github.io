import assert from 'node:assert/strict';
import { readFile, access } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { publicDataSchema } from '../src/data/schema.ts';
import { pagePath } from '../src/lib/i18n.ts';

const root = fileURLToPath(new URL('../', import.meta.url));
const dist = path.join(root, 'dist');
const origin = 'https://kmraven.github.io';
const data = publicDataSchema.parse(JSON.parse(await readFile(path.join(root, 'src/data/researchmap.public.json'), 'utf8')));
const pages = new Map<string, string>();
const fileFor = (pathname: string) => path.join(dist, pathname.endsWith('/') ? `${pathname}index.html` : pathname);
for (const lang of ['ja', 'en'] as const) {
  for (const page of ['home', 'publications', 'cv'] as const) {
    const route = pagePath(page, lang);
    const html = await readFile(fileFor(route), 'utf8');
    pages.set(route, html);
    assert(html.includes(`<html lang="${lang}">`), `Wrong document language: ${route}`);
    assert.equal((html.match(/<h1(?:\s|>)/g) ?? []).length, 1, `Expected one h1: ${route}`);
    assert(/<title>[^<]+<\/title>/.test(html), `Missing title: ${route}`);
    assert(/<meta name="description" content="[^"]+"/.test(html), `Missing description: ${route}`);
    assert(html.includes(`rel="canonical" href="${origin}${route}"`), `Wrong canonical: ${route}`);
    const other = lang === 'ja' ? 'en' : 'ja';
    assert(html.includes(`hreflang="${other}" href="${origin}${pagePath(page, other)}"`), `Wrong alternate: ${route}`);
    assert(html.includes(`href="${pagePath(page, other)}" lang="${other}"`), `Language switch loses page: ${route}`);
    assert(!/user_id|display_erad_id|affiliation_type|effort_rate|PRIVATE_TEST/.test(html), `Internal fields leaked: ${route}`);
    if (page === 'publications' || page === 'cv') {
      assert.equal((html.match(/data-record="publication"/g) ?? []).length, data.publications.length, `Paper count mismatch: ${route}`);
      assert.equal((html.match(/data-record="presentation"/g) ?? []).length, data.presentations.length, `Presentation count mismatch: ${route}`);
    }
    if (page === 'cv') {
      assert.equal((html.match(/data-record="education"/g) ?? []).length, data.education.length, `Education count mismatch: ${route}`);
      assert.equal((html.match(/data-record="experience"/g) ?? []).length, data.experience.length, `Experience count mismatch: ${route}`);
    }
  }
}
for (const [route, html] of pages) {
  for (const match of html.matchAll(/\b(?:href|src)="([^"]+)"/g)) {
    const url = new URL(match[1].replaceAll('&amp;', '&'), `${origin}${route}`);
    if (url.origin !== origin) continue;
    await access(fileFor(url.pathname));
    if (url.hash) {
      const target = pages.get(url.pathname) ?? await readFile(fileFor(url.pathname), 'utf8');
      assert(target.includes(`id="${decodeURIComponent(url.hash.slice(1))}"`), `Broken anchor: ${route} → ${url.href}`);
    }
  }
}
const sitemapIndex = await readFile(path.join(dist, 'sitemap-index.xml'), 'utf8');
assert(sitemapIndex.includes(`${origin}/sitemap-0.xml`));
const sitemap = await readFile(path.join(dist, 'sitemap-0.xml'), 'utf8');
for (const route of pages.keys()) assert(sitemap.includes(`<loc>${origin}${route}</loc>`), `Missing sitemap route: ${route}`);
const tracked = spawnSync('git', ['ls-files', '-z'], { cwd: root, encoding: 'utf8' });
if (tracked.status === 0) {
  const unsafe = tracked.stdout.split('\0').filter((file) => /\.(?:jsonl|zip)$/i.test(file) || /(?:^|\/)\.DS_Store$/.test(file) || file.startsWith('private/'));
  assert.equal(unsafe.length, 0, 'Original exports or private files are tracked by Git');
}
console.log(`Verified ${pages.size} pages: metadata, language links, output counts, local assets, anchors, sitemap, and publication safety.`);
