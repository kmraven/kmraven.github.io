import { execFileSync } from 'node:child_process';
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { parseFrontmatter } from 'astro/markdown';

export interface AboutRevision {
  date: string;
  body: string;
  source: string;
}

// A checkout's filesystem dates describe the checkout, not the last content edit.
export function aboutDate(value: Date | string): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date(value));
}

function publicBody(source: string): string | undefined {
  const { frontmatter, content } = parseFrontmatter(source);
  if (frontmatter.published !== true || !content.replace(/<!--[\s\S]*?-->/g, '').trim()) return;
  return content;
}

export async function readAboutRevisions(root: string, lang: 'ja' | 'en'): Promise<AboutRevision[]> {
  const relative = `content/about/${lang}.md`;
  const file = path.join(root, relative);
  let source: string;
  try { source = await readFile(file, 'utf8'); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [];
    throw error;
  }
  if (publicBody(source) === undefined) return [];
  const git = (...args: string[]) => execFileSync('git', args, {
    cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
  }).trimEnd();
  let inGit = false;
  try { inGit = git('rev-parse', '--is-inside-work-tree') === 'true'; } catch { /* Source-only preview. */ }
  const snapshots: { date: string; source: string }[] = [];
  if (inGit) {
    if (git('rev-parse', '--is-shallow-repository') === 'true') {
      throw new Error('About dates require full Git history. Check out with fetch-depth: 0.');
    }
    const log = git('log', '--format=%H %cI', '--diff-filter=AM', '--', relative);
    for (const line of log.split('\n').filter(Boolean)) {
      const [commit, timestamp] = line.split(' ');
      // Do not trim file content: it must match the working file byte for byte.
      const content = execFileSync('git', ['show', `${commit}:${relative}`], {
        cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
      });
      snapshots.push({ date: aboutDate(timestamp), source: content });
    }
  }
  if (snapshots[0]?.source !== source) {
    snapshots.unshift({ date: aboutDate((await stat(file)).mtime), source });
  }
  const seenDates = new Set<string>();
  const revisions: AboutRevision[] = [];
  for (const snapshot of snapshots) {
    // At most one version per day, including days whose last version was a draft.
    if (seenDates.has(snapshot.date)) continue;
    seenDates.add(snapshot.date);
    const body = publicBody(snapshot.source);
    if (body !== undefined) revisions.push({ ...snapshot, body });
  }
  return revisions;
}
