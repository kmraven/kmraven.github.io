import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';
import { isPartialDate, historySchema } from './data/schema';

const research = defineCollection({
  loader: glob({ pattern: '{ja,en}.md', base: './content/research' }),
  schema: z.object({ title: z.string(), published: z.boolean().default(false) }),
});

const about = defineCollection({
  loader: glob({ pattern: '{ja,en}.md', base: './content/about' }),
  schema: z.object({ published: z.boolean().default(false) }),
});

const profileUrl = z.string().trim().pipe(z.union([
  z.literal(''),
  z.url().refine((url) => /^https?:\/\//.test(url), 'Only HTTP(S) URLs are allowed'),
])).default('');

const profile = defineCollection({
  loader: glob({ pattern: 'profile.md', base: './content' }),
  schema: ({ image }) => z.strictObject({
    photo: image().optional(),
    current_lab: z.string().trim().default(''),
    links: z.strictObject({
      github: profileUrl, x: profileUrl, linkedin: profileUrl, google_scholar: profileUrl,
    }),
  }),
});

const history = defineCollection({
  loader: glob({ pattern: 'history.md', base: './content' }),
  schema: z.strictObject({
    entries: z.array(z.strictObject({
      id: z.string().regex(/^[a-z0-9-]+$/),
      category: z.enum(['education', 'experience']),
      match: z.strictObject({
        organization: z.string().trim().min(1),
        start: z.string().refine(isPartialDate, 'Invalid start date'),
      }),
      lab: z.strictObject({
        name: z.strictObject({ ja: z.string().trim(), en: z.string().trim() }),
        url: profileUrl,
      }),
    })).superRefine((entries, context) => {
      const ids = new Set<string>();
      const matches = new Set<string>();
      entries.forEach((entry, index) => {
        const match = JSON.stringify([entry.category, entry.match.organization, entry.match.start]);
        if (ids.has(entry.id) || matches.has(match)) {
          context.addIssue({ code: 'custom', path: [index], message: 'History IDs and matching records must be unique' });
        }
        ids.add(entry.id);
        matches.add(match);
      });
    }),
  }),
});

const career = defineCollection({
  loader: glob({ pattern: '{ja,en}.md', base: './content/career' }),
  schema: z.strictObject({ title: z.string(), published: z.boolean().default(false) }),
});

const education = defineCollection({
  loader: glob({ pattern: 'education.md', base: './content' }),
  schema: z.strictObject({ entries: z.array(historySchema) }),
});

const music = defineCollection({
  loader: glob({ pattern: '{ja,en}.md', base: './content/music' }),
  schema: z.strictObject({ title: z.string(), apple_music: profileUrl }),
});

export const collections = { research, about, profile, history, career, education, music };
