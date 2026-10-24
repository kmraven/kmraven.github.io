import test from 'node:test';
import assert from 'node:assert/strict';
import { currentLab, historySupplement, type HistorySupplement } from '../src/lib/history-supplements.ts';

const university = { ja: '大学', en: 'University' };
const first: HistorySupplement = {
  id: 'first', category: 'education', match: { organization: '大学', start: '2020-04' },
  lab: { name: { en: 'First Lab' }, url: '' },
};
const second: HistorySupplement = {
  id: 'second', category: 'education', match: { organization: 'University', start: '2024-04' },
  lab: { name: { en: 'Second Lab' }, url: '' },
};

test('history supplements follow the institution and start date, independently of order and end date', () => {
  const item = { organization: university, start: '2020-04', end: '2024-03' };
  assert.equal(historySupplement(item, 'education', [second, first])?.lab.name.en, 'First Lab');
  assert.equal(historySupplement({ ...item, end: null }, 'education', [first, second])?.lab.name.en, 'First Lab');
  assert.equal(historySupplement({ ...item, start: '2024-04' }, 'education', [first, second])?.lab.name.en, 'Second Lab');
  assert.equal(historySupplement(item, 'experience', [first, second]), undefined);
});

test('the current lab is shown only while its selected history record remains public', () => {
  const data = { education: [{ organization: university, start: '2024-04', end: null }], experience: [] };
  assert.equal(currentLab('second', [first, second], data)?.name.en, 'Second Lab');
  assert.equal(currentLab('first', [first, second], data), undefined);
  assert.equal(currentLab('second', [first, second], { education: [], experience: [] }), undefined);
  assert.equal(currentLab('', [first, second], data), undefined);
});
