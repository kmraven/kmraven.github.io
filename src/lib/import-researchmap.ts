import { z } from 'zod';
import {
  publicDataSchema, type PublicData, type LocalizedText, type LocalizedAuthors,
  type ResourceLink, type History,
} from '../data/schema.ts';

const objectSchema = z.record(z.string(), z.unknown());
const envelopeSchema = z.object({
  insert: z.object({ type: z.string().min(1), id: z.union([z.string().min(1), z.number().int()]) }),
  merge: objectSchema,
});
const supported = new Set(['researchers', 'research_areas', 'research_experience', 'education', 'published_papers', 'presentations']);

export class ImportError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ImportError';
  }
}

function object(value: unknown): Record<string, unknown> {
  return objectSchema.parse(value);
}

function text(value: unknown): LocalizedText | undefined {
  if (value === undefined || value === null || value === '') return undefined;
  const source = object(value);
  const result: LocalizedText = {};
  for (const lang of ['ja', 'en'] as const) {
    const entry = source[lang];
    if (entry === undefined || entry === null || entry === '') continue;
    const parsed = z.string().parse(entry).trim();
    if (parsed) result[lang] = parsed;
  }
  return result.ja || result.en ? result : undefined;
}

function requiredText(value: unknown): LocalizedText {
  const result = text(value);
  if (!result) throw new ImportError('A required multilingual field is empty');
  return result;
}

function authors(value: unknown): LocalizedAuthors {
  const source = object(value);
  const result: LocalizedAuthors = {};
  for (const lang of ['ja', 'en'] as const) {
    if (source[lang] === undefined) continue;
    const entries = z.array(z.object({ name: z.string().trim().min(1) })).parse(source[lang]);
    if (entries.length) result[lang] = entries.map((entry) => entry.name);
  }
  if (!result.ja && !result.en) throw new ImportError('An author list is required');
  return result;
}

function optionalDate(value: unknown): string | undefined {
  if (value === undefined || value === null || value === '') return undefined;
  return z.string().parse(value);
}

function history(source: Record<string, unknown>, category: 'experience' | 'education'): History {
  return {
    organization: requiredText(source.affiliation),
    department: text(category === 'experience' ? source.section : source.department),
    course: category === 'education' ? text(source.course) : undefined,
    start: optionalDate(source.from_date),
    end: source.to_date === '9999' ? null : optionalDate(source.to_date),
  };
}

function safeUrl(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return undefined;
    if (['arxiv.org', 'doi.org', 'github.com'].includes(url.hostname)) url.protocol = 'https:';
    return url.href;
  } catch { return undefined; }
}

function identifiers(source: Record<string, unknown>): Record<string, unknown> {
  return source.identifiers === undefined ? {} : object(source.identifiers);
}

function firstIdentifier(source: Record<string, unknown>, key: string): string | undefined {
  const value = source[key];
  if (value === undefined) return undefined;
  return z.array(z.string()).parse(value)[0]?.trim();
}

function publicationResources(source: Record<string, unknown>) {
  const ids = identifiers(source);
  const arxiv = firstIdentifier(ids, 'arxiv_id')?.replace(/^arxiv:/i, '');
  const doi = firstIdentifier(ids, 'doi')?.replace(/^https?:\/\/(?:dx\.)?doi\.org\//, '');
  const hasArxiv = Boolean(arxiv && /^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?\/\d{7})(?:v\d+)?$/i.test(arxiv));
  const hasDoi = Boolean(doi && /^10\.\d{4,9}\/\S+$/i.test(doi));
  const links: ResourceLink[] = [];
  if (hasDoi) links.push({ label: 'Paper', url: `https://doi.org/${doi}` });
  if (hasArxiv) links.push({ label: 'arXiv', url: `https://arxiv.org/abs/${arxiv}` });
  const resources = source.see_also === undefined ? [] : z.array(objectSchema).parse(source.see_also);
  for (const resource of resources) {
    const url = safeUrl(resource['@id']);
    if (!url) continue;
    const parsed = new URL(url);
    if (parsed.hostname === 'arxiv.org') {
      if (parsed.pathname.includes('arXiv:')) continue;
      if (hasArxiv && parsed.pathname.startsWith('/abs/')) continue;
    }
    const downloadable = resource.is_downloadable === true || /\.pdf(?:$|[?#])/i.test(url) || /^https:\/\/arxiv\.org\/pdf\//.test(url);
    const label = downloadable ? 'PDF' : parsed.hostname === 'github.com' ? 'Code' : 'Link';
    if (links.some((link) => link.url === url || (label === 'PDF' && link.label === 'PDF'))) continue;
    links.push({ label, url });
  }
  if (hasArxiv && !links.some((link) => link.label === 'PDF')) {
    links.push({ label: 'PDF', url: `https://arxiv.org/pdf/${arxiv}` });
  }
  // A repository explicitly named in a public abstract is a resource of that paper.
  const abstract = text(source.description);
  for (const content of Object.values(abstract ?? {})) {
    for (const match of content.matchAll(/https:\/\/github\.com\/[\w.-]+\/[\w.-]+/g)) {
      const url = safeUrl(match[0].replace(/[.]+$/, ''));
      if (url && !links.some((link) => link.url === url)) links.push({ label: 'Code', url });
    }
  }
  return { links, isArxivOnly: hasArxiv && !hasDoi && !text(source.publication_name) };
}

function profile(source: Record<string, unknown>): PublicData['profile'] {
  const permalink = z.string().regex(/^[a-zA-Z0-9_-]+$/).parse(source.permalink);
  const links: ResourceLink[] = [{ label: 'researchmap', url: `https://researchmap.jp/${permalink}` }];
  // Do not reuse see_also: an ORCID link must respect its own visibility flag.
  if (source.display_orc_id === 'disclosed') {
    const orcid = firstIdentifier(identifiers(source), 'orc_id');
    if (orcid && /^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/i.test(orcid)) {
      links.push({ label: 'ORCID', url: `https://orcid.org/${orcid}` });
    }
  }
  const affiliations = source.affiliations === undefined ? [] : z.array(objectSchema).parse(source.affiliations);
  return {
    familyName: requiredText(source.family_name),
    givenName: requiredText(source.given_name),
    affiliations: affiliations.filter((entry) => entry.display_affiliation === 'disclosed').map((entry) => ({
      organization: requiredText(entry.affiliation),
      department: text(entry.section),
      position: entry.display_job === 'disclosed' ? text(entry.job) : undefined,
    })),
    links,
  };
}

function descendingDate(a: { date?: string }, b: { date?: string }) {
  return (b.date ?? '').localeCompare(a.date ?? '');
}

function descendingHistory(a: History, b: History) {
  return (b.start ?? '').localeCompare(a.start ?? '');
}

export function importResearchmap(input: string): { data: PublicData; report: { included: Record<string, number>; hidden: number; unsupported: Record<string, number> } } {
  const data: PublicData = {
    schemaVersion: 1,
    profile: undefined as unknown as PublicData['profile'],
    researchAreas: [], experience: [], education: [], publications: [], presentations: [],
  };
  const report = { included: {} as Record<string, number>, hidden: 0, unsupported: {} as Record<string, number> };
  const seen = new Set<string>();
  let profiles = 0;
  const lines = input.replace(/^\uFEFF/, '').split(/\r?\n/);
  lines.forEach((line, index) => {
    if (!line.trim()) return;
    try {
      const record = envelopeSchema.parse(JSON.parse(line));
      const { type, id } = record.insert;
      const source = record.merge;
      if (!supported.has(type)) {
        report.unsupported[type] = (report.unsupported[type] ?? 0) + 1;
        return;
      }
      const identity = `${type}:${id}`;
      if (seen.has(identity)) throw new ImportError('Duplicate record; a complete snapshot is required');
      seen.add(identity);
      if (type !== 'researchers' && source.display !== 'disclosed') {
        report.hidden++;
        return;
      }
      switch (type) {
        case 'researchers':
          if (++profiles !== 1) throw new ImportError('Only one researcher is supported');
          data.profile = profile(source);
          break;
        case 'research_areas':
          data.researchAreas.push({ discipline: text(source.discipline), field: requiredText(source.research_field) });
          break;
        case 'research_experience': data.experience.push(history(source, 'experience')); break;
        case 'education': data.education.push(history(source, 'education')); break;
        case 'published_papers': {
          const resources = publicationResources(source);
          data.publications.push({
            title: requiredText(source.paper_title), authors: authors(source.authors),
            date: optionalDate(source.publication_date), venue: text(source.publication_name),
            kind: resources.isArxivOnly ? 'preprint' : 'paper',
            abstract: text(source.description), links: resources.links,
          });
          break;
        }
        case 'presentations':
          data.presentations.push({
            title: requiredText(source.presentation_title), authors: authors(source.presenters),
            event: text(source.event), date: optionalDate(source.publication_date),
            type: source.presentation_type === 'poster_presentation' ? 'poster'
              : source.presentation_type === 'oral_presentation' ? 'oral' : 'other',
          });
          break;
      }
      report.included[type] = (report.included[type] ?? 0) + 1;
    } catch (error) {
      if (error instanceof ImportError) throw new ImportError(`Line ${index + 1}: ${error.message}`);
      // Validation errors can contain private input values. Report locations, never values.
      const fields = error instanceof z.ZodError ? error.issues.map((issue) => issue.path.join('.')).filter(Boolean).join(', ') : '';
      throw new ImportError(`Line ${index + 1}: Invalid record${fields ? ` (fields: ${fields})` : ''}`);
    }
  });
  if (profiles !== 1) throw new ImportError('Exactly one researcher profile is required');
  data.experience.sort(descendingHistory);
  data.education.sort(descendingHistory);
  data.publications.sort(descendingDate);
  data.presentations.sort(descendingDate);
  const result = publicDataSchema.safeParse(data);
  if (!result.success) {
    throw new ImportError(`Invalid public data (fields: ${result.error.issues.map((issue) => issue.path.join('.')).join(', ')})`);
  }
  return { data: result.data, report };
}
