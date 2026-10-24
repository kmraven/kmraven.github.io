import { z } from 'zod';

export const locales = ['ja', 'en'] as const;
export type Locale = (typeof locales)[number];

export const localizedTextSchema = z.strictObject({
  ja: z.string().trim().min(1).optional(),
  en: z.string().trim().min(1).optional(),
}).refine((value) => Boolean(value.ja || value.en), 'At least one supported language is required');

export function isPartialDate(value: string): boolean {
  if (!/^\d{4}(?:-\d{2}(?:-\d{2})?)?$/.test(value)) return false;
  const [year, month, day] = value.split('-').map(Number);
  if (year < 1000 || year > 9998) return false;
  if (month === undefined) return true;
  if (month < 1 || month > 12) return false;
  if (day === undefined) return true;
  return day >= 1 && day <= new Date(Date.UTC(year, month, 0)).getUTCDate();
}

export const partialDateSchema = z.string().refine(isPartialDate, 'Invalid partial date');
const urlSchema = z.url().refine((value) => /^https?:\/\//.test(value), 'Only HTTP(S) URLs are allowed');
export const linkSchema = z.strictObject({
  label: z.enum(['researchmap', 'ORCID', 'Paper', 'arXiv', 'PDF', 'Code', 'Link']),
  url: urlSchema,
});
const localizedAuthorsSchema = z.strictObject({
  ja: z.array(z.string().trim().min(1)).min(1).optional(),
  en: z.array(z.string().trim().min(1)).min(1).optional(),
}).refine((value) => Boolean(value.ja || value.en), 'At least one author list is required');

export const affiliationSchema = z.strictObject({
  organization: localizedTextSchema,
  department: localizedTextSchema.optional(),
  position: localizedTextSchema.optional(),
});
export const historySchema = z.strictObject({
  organization: localizedTextSchema,
  department: localizedTextSchema.optional(),
  course: localizedTextSchema.optional(),
  start: partialDateSchema.optional(),
  end: partialDateSchema.nullable().optional(),
});
export const publicationSchema = z.strictObject({
  title: localizedTextSchema,
  authors: localizedAuthorsSchema,
  date: partialDateSchema.optional(),
  venue: localizedTextSchema.optional(),
  kind: z.enum(['paper', 'preprint']),
  abstract: localizedTextSchema.optional(),
  links: z.array(linkSchema),
});
export const presentationSchema = z.strictObject({
  title: localizedTextSchema,
  authors: localizedAuthorsSchema,
  event: localizedTextSchema.optional(),
  date: partialDateSchema.optional(),
  type: z.enum(['poster', 'oral', 'other']),
});

export const publicDataSchema = z.strictObject({
  schemaVersion: z.literal(1),
  profile: z.strictObject({
    familyName: localizedTextSchema,
    givenName: localizedTextSchema,
    affiliations: z.array(affiliationSchema),
    links: z.array(linkSchema),
  }),
  researchAreas: z.array(z.strictObject({
    discipline: localizedTextSchema.optional(),
    field: localizedTextSchema,
  })),
  experience: z.array(historySchema),
  education: z.array(historySchema),
  publications: z.array(publicationSchema),
  presentations: z.array(presentationSchema),
});

export type LocalizedText = z.infer<typeof localizedTextSchema>;
export type LocalizedAuthors = z.infer<typeof localizedAuthorsSchema>;
export type PublicData = z.infer<typeof publicDataSchema>;
export type Profile = PublicData['profile'];
export type History = z.infer<typeof historySchema>;
export type Publication = z.infer<typeof publicationSchema>;
export type Presentation = z.infer<typeof presentationSchema>;
export type ResourceLink = z.infer<typeof linkSchema>;
