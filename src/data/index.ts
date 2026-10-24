import raw from './researchmap.public.json';
import { publicDataSchema } from './schema.ts';

export const data = publicDataSchema.parse(raw);
