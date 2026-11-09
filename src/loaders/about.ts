import type { Loader } from 'astro/loaders';
import { fileURLToPath } from 'node:url';
import { readAboutRevisions } from '../lib/about-history.ts';

export function aboutLoader(): Loader {
  return {
    name: 'about-git-history',
    async load({ config, store, parseData, renderMarkdown, watcher, logger }) {
      const root = fileURLToPath(config.root);
      async function sync() {
        const entries = [];
        for (const lang of ['ja', 'en'] as const) {
          const filePath = `content/about/${lang}.md`;
          const revisions = await readAboutRevisions(root, lang);
          for (const [index, revision] of revisions.entries()) {
            const id = index === 0 ? lang : `${lang}-${revision.date}`;
            const data = await parseData({ id, filePath, data: {
              lang, date: revision.date, latest: index === 0, published: true,
            } });
            const rendered = await renderMarkdown(revision.source, { fileURL: new URL(filePath, config.root) });
            entries.push({ id, data, body: revision.body, filePath, rendered,
              assetImports: rendered.metadata?.imagePaths });
          }
        }
        store.clear();
        for (const entry of entries) store.set(entry);
      }
      await sync();
      if (watcher) {
        // Serialize updates so rapid saves cannot leave an older snapshot in the store.
        let pending = Promise.resolve();
        const files = ['ja', 'en'].map(lang => fileURLToPath(new URL(`content/about/${lang}.md`, config.root)));
        watcher.add(files);
        watcher.on('all', (_event, file) => {
          if (!files.includes(file)) return;
          pending = pending.then(sync).catch(error => logger.error(String(error)));
        });
      }
    },
  };
}
