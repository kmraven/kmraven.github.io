import test from 'node:test';
import assert from 'node:assert/strict';
import { importResearchmap, ImportError } from '../src/lib/import-researchmap.ts';
import { publicDataSchema, isPartialDate } from '../src/data/schema.ts';
import { record, snapshot, sampleProfile, examplePaper } from './fixtures.ts';

test('uses an allowlist for profile fields and honors nested visibility', () => {
  const { data } = importResearchmap(snapshot());
  assert.equal(data.profile.affiliations.length, 1);
  assert.equal(data.profile.affiliations[0].position, undefined);
  assert.equal(data.profile.links.length, 2);
  assert(!JSON.stringify(data).includes('PRIVATE_TEST'));
  assert(!JSON.stringify(data).includes('user_id'));
  assert.equal(data.profile.familyName.en, 'RESEARCHER');
});

test('a restricted ORCID cannot leak through profile links', () => {
  const input = JSON.stringify(record('researchers', 1, {
    ...sampleProfile,
    display_orc_id: 'researchers_only',
    see_also: [{ label: 'orcid', '@id': 'https://orcid.org/0009-0005-1321-2218' }],
  }));
  const { data } = importResearchmap(input);
  assert.deepEqual(data.profile.links.map((link) => link.label), ['researchmap']);
  assert(!JSON.stringify(data).includes('0009-0005-1321-2218'));
});

test('only explicitly disclosed records are included', () => {
  const visible = { display: 'disclosed', affiliation: { en: 'Public University' }, from_date: '2026-04', to_date: '9999' };
  const { data, report } = importResearchmap(snapshot(
    record('education', 2, visible),
    record('education', 3, { ...visible, display: 'closed', affiliation: { en: 'PRIVATE_TEST_SCHOOL' } }),
    record('education', 4, { ...visible, display: 'researchers_only' }),
    record('education', 5, { ...visible, display: undefined }),
  ));
  assert.equal(data.education.length, 1);
  assert.equal(data.education[0].end, null);
  assert.equal(report.hidden, 3);
  assert(!JSON.stringify(data).includes('PRIVATE_TEST'));
});

test('full regeneration reflects deletions and visibility changes', () => {
  const row = record('education', 2, { display: 'disclosed', affiliation: { en: 'Public University' } });
  assert.equal(importResearchmap(snapshot(row)).data.education.length, 1);
  assert.equal(importResearchmap(snapshot()).data.education.length, 0);
  row.merge.display = 'closed';
  assert.equal(importResearchmap(snapshot(row)).data.education.length, 0);
});

test('classifies arXiv-only work as a preprint and normalizes resource links', () => {
  const { data } = importResearchmap(snapshot(record('published_papers', 2, examplePaper)));
  const item = data.publications[0];
  assert.equal(item.kind, 'preprint');
  assert.deepEqual(item.title, { en: 'An example preprint' });
  assert.deepEqual(item.links, [
    { label: 'arXiv', url: 'https://arxiv.org/abs/2607.10537' },
    { label: 'PDF', url: 'https://arxiv.org/pdf/2607.10537v1' },
    { label: 'Code', url: 'https://github.com/example/research-code' },
  ]);
});

test('does not assume that work with a DOI is a preprint', () => {
  const { data } = importResearchmap(snapshot(record('published_papers', 2, {
    ...examplePaper, identifiers: { arxiv_id: ['2607.10537'], doi: ['10.1234/example'] },
  })));
  assert.equal(data.publications[0].kind, 'paper');
  assert.equal(data.publications[0].links[0].url, 'https://doi.org/10.1234/example');
});

test('rejects unsafe URLs while preserving safe resource links', () => {
  const { data } = importResearchmap(snapshot(record('published_papers', 2, {
    ...examplePaper, identifiers: {}, description: undefined,
    see_also: [
      { '@id': 'javascript:alert(1)' },
      { '@id': 'data:text/html,example' },
      { '@id': 'https://user:password@example.invalid/' },
      { '@id': 'https://example.org/paper.pdf', is_downloadable: true },
    ],
  })));
  assert.deepEqual(data.publications[0].links, [{ label: 'PDF', url: 'https://example.org/paper.pdf' }]);
});

test('preserves date precision, future experience, and both source languages', () => {
  const { data } = importResearchmap(snapshot(
    record('research_experience', 2, { display: 'disclosed', affiliation: { ja: '機構', en: 'Organization' }, section: { en: 'Research Fellow (DC2)' }, from_date: '2027-04', to_date: '2029-03' }),
    record('presentations', 3, { display: 'disclosed', presentation_title: { ja: '発表例' }, presenters: { ja: [{ name: '研究例' }] }, publication_date: '2026-09', presentation_type: 'poster_presentation' }),
    record('presentations', 4, { display: 'disclosed', presentation_title: { en: 'An earlier presentation' }, presenters: { en: [{ name: 'Example Researcher' }] }, publication_date: '2025', presentation_type: 'oral_presentation' }),
  ));
  assert.equal(data.experience[0].start, '2027-04');
  assert.equal(data.experience[0].end, '2029-03');
  assert.equal(data.presentations[0].date, '2026-09');
  assert.equal(data.presentations[0].title.en, undefined);
  assert.equal(data.presentations[1].date, '2025');
});

test('supports BOM and CRLF, and gives deterministic output', () => {
  const input = snapshot(record('published_papers', 2, examplePaper));
  assert.deepEqual(importResearchmap(`\uFEFF${input.replaceAll('\n', '\r\n')}\r\n`).data, importResearchmap(input).data);
});

test('unsupported categories are skipped with a count', () => {
  const { data, report } = importResearchmap(snapshot(record('awards', 2, { award_name: { en: 'PRIVATE_TEST_AWARD' } })));
  assert.deepEqual(report.unsupported, { awards: 1 });
  assert(!JSON.stringify(data).includes('PRIVATE_TEST'));
});

test('malformed records, duplicate records, and invalid dates fail without exposing their values', () => {
  assert.throws(() => importResearchmap('PRIVATE_TEST_INVALID_JSON'), /Line 1: Invalid record/);
  assert.throws(() => importResearchmap(''), /Exactly one researcher/);
  assert.throws(() => importResearchmap(snapshot(record('researchers', 2, sampleProfile))), /Only one researcher/);
  assert.throws(() => importResearchmap(snapshot(record('education', 2, { display: 'disclosed', affiliation: { en: 'Test' } }), record('education', 2, { display: 'disclosed' }))), /Duplicate record/);
  for (const invalid of ['2026-13', '2025-02-29', '2026-04-31', '9999', 'PRIVATE_TEST_INVALID_DATE']) {
    assert.throws(() => importResearchmap(snapshot(record('published_papers', 2, { ...examplePaper, publication_date: invalid }))), (error: unknown) => {
      assert(error instanceof ImportError);
      assert(!error.message.includes(invalid));
      return true;
    });
  }
});

test('public data schema rejects additional fields rather than silently publishing them', () => {
  const { data } = importResearchmap(snapshot());
  assert.equal(publicDataSchema.safeParse({ ...data, account: 'PRIVATE_TEST_ACCOUNT' }).success, false);
  assert.equal(publicDataSchema.safeParse({ ...data, profile: { ...data.profile, email: 'PRIVATE_TEST_EMAIL' } }).success, false);
});

test('validates real calendar dates without adding a day to year/month inputs', () => {
  for (const valid of ['2026', '2026-09', '2024-02-29', '2026-09-30']) assert(isPartialDate(valid));
  for (const invalid of ['2026-00', '2026-9', '2026-02-29', '2026-09-31']) assert(!isPartialDate(invalid));
});
