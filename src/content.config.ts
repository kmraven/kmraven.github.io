import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

const research = defineCollection({
  loader: glob({ pattern: '{ja,en}.md', base: './src/content/research' }),
  schema: z.object({ title: z.string(), published: z.boolean().default(false) }),
});

export const collections = { research };
