import raw from './researchmap.public.json';
import { publicDataSchema } from './schema.ts';

export const data = publicDataSchema.parse(raw);
export const profileLinks = [
  ...data.profile.links,
  { label: 'GitHub', url: 'https://github.com/kmraven' },
];
