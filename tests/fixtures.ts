export function record(type: string, id: number, merge: Record<string, unknown>) {
  return { insert: { type, id, user_id: 'PRIVATE_TEST_INTERNAL_USER' }, merge };
}

export const sampleProfile = {
  permalink: 'sample-researcher',
  family_name: { ja: '研究', en: 'RESEARCHER', 'ja-Kana': 'PRIVATE_TEST_KANA' },
  given_name: { ja: '例', en: 'Example' },
  display_orc_id: 'disclosed',
  identifiers: { orc_id: ['0009-0005-1321-2218'], erad_id: ['PRIVATE_TEST_ERAD'] },
  display_erad_id: 'researchers_only',
  email: 'PRIVATE_TEST_EMAIL@example.invalid',
  affiliations: [
    { affiliation: { en: 'Example University' }, section: { en: 'Example Department' }, display_affiliation: 'disclosed', display_job: 'closed', job: { en: 'PRIVATE_TEST_JOB' }, affiliation_type: 'PRIVATE_TEST_TYPE', effort_rate: 'PRIVATE_TEST_EFFORT' },
    { affiliation: { en: 'PRIVATE_TEST_AFFILIATION' }, display_affiliation: 'closed', display_job: 'disclosed' },
  ],
  see_also: [{ label: 'url', '@id': 'https://example.invalid/PRIVATE_TEST_URL' }],
};

export function snapshot(...rows: ReturnType<typeof record>[]) {
  return [record('researchers', 1, sampleProfile), ...rows].map((row) => JSON.stringify(row)).join('\n');
}

export const examplePaper = {
  display: 'disclosed',
  paper_title: { en: 'An example preprint' },
  authors: { en: [{ name: 'Example Researcher' }] },
  publication_date: '2026-07-12',
  identifiers: { arxiv_id: ['arXiv:2607.10537'] },
  see_also: [
    { label: 'arxiv', '@id': 'http://arxiv.org/abs/arXiv:2607.10537' },
    { label: 'url', '@id': 'https://arxiv.org/abs/2607.10537v1' },
    { label: 'url', '@id': 'https://arxiv.org/pdf/2607.10537v1', is_downloadable: true },
  ],
  description: { en: 'Code is available at https://github.com/example/research-code .' },
};
