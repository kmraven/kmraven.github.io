import test from 'node:test';
import assert from 'node:assert/strict';
import { authorNames, translated, fullName, formatDate, formatPeriod, pagePath, hasResearchContent, pageDescription } from '../src/lib/i18n.ts';

test('uses source language when the requested translation is absent', () => {
  assert.deepEqual(translated({ en: 'Original title' }, 'ja'), { text: 'Original title', lang: 'en' });
  assert.deepEqual(translated({ ja: '原題' }, 'en'), { text: '原題', lang: 'ja' });
  assert.deepEqual(authorNames({ ja: ['研究例'] }, 'en'), { names: ['研究例'], lang: 'ja' });
});
test('formats names and dates with the original precision', () => {
  const person = { familyName: { ja: '研究', en: 'RESEARCHER' }, givenName: { ja: '例', en: 'Example' } };
  assert.equal(fullName(person, 'ja'), '研究例');
  assert.equal(fullName(person, 'en'), 'Example Researcher');
  assert.equal(formatDate('2026', 'ja'), '2026年');
  assert.equal(formatDate('2026-09', 'en'), 'Sep 2026');
  assert.equal(formatDate('2026-07-12', 'ja'), '2026年7月12日');
  assert.equal(formatPeriod('2026-04', null, 'ja'), '2026年4月 – 現在');
  assert.equal(formatPeriod('2027-04', '2029-03', 'en'), 'Apr 2027 – Mar 2029');
  assert.equal(formatPeriod('2024', undefined, 'en'), '2024');
});
test('language links preserve the current page', () => {
  assert.equal(pagePath('home', 'ja'), '/');
  assert.equal(pagePath('home', 'en'), '/en/');
  assert.equal(pagePath('cv', 'en'), '/en/cv/');
  assert.equal(pagePath('cv', 'ja'), '/cv/');
  assert.equal(pagePath('misc', 'ja'), '/misc/');
  assert.equal(pagePath('misc', 'en'), '/en/misc/');
});
test('unpublished or empty research introductions stay hidden', () => {
  assert.equal(hasResearchContent(false, 'A research introduction'), false);
  assert.equal(hasResearchContent(true, '  <!-- Instructions -->\n'), false);
  assert.equal(hasResearchContent(true, undefined), false);
  assert.equal(hasResearchContent(true, 'An introduction'), true);
});
test('metadata derives the researcher name from the shared profile', () => {
  assert(pageDescription('home', 'en', 'Example Researcher').startsWith('Example Researcher.'));
  assert(pageDescription('cv', 'ja', '研究例').startsWith('研究例の'));
});
