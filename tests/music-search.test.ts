import assert from 'node:assert/strict';
import test from 'node:test';
import { indexHistory } from '../src/components/music-map/model.ts';
import { buildSearchIndex, searchLibrary } from '../src/components/music-map/search.ts';

test('alternate titles and joint credits match the corresponding recording in the selected year', () => {
  const catalog = indexHistory({
    start: '', end: '', relation: 'none', edges: [],
    tracks: [
      { id: '1', title: 'Sun', titleAliases: ['太陽', 'サン'], artist: 'A', credit: 'A & B', group: 'Pop', years: { 2023: 10 } },
      { id: '2', title: 'Solo', artist: 'A', group: 'Pop', years: { 2024: 20 } },
      { id: '3', title: 'Moon', artist: 'B', group: 'Pop', years: { 2024: 30 } },
    ],
  });
  const index = buildSearchIndex(catalog);
  const search = (query: string, year = '') => searchLibrary(index, query, year);

  assert.deepEqual(search('太陽 B').map(hit => hit.item.id), ['1']);
  assert.equal(search('ｻﾝ')[0].titleAlias, 'サン');
  assert.equal(search('B')[0].item.kind, 'artist');
  assert.deepEqual(search('B').filter(hit => hit.item.kind === 'track').map(hit => hit.item.name), ['Moon', 'Sun']);
  assert.deepEqual(search('太陽', '2024'), []);
  assert.equal(search('１')[0].item.credit, 'A & B');
});

test('artist placement, shared styles and Apple track genres remain distinct', () => {
  const catalog = indexHistory({
    start: '', end: '', relation: 'style', edges: [['Band', 'Peer', ['alternative rock'], 0.9]],
    artistStyles: {
      Band: { method: 'style', tags: { musicbrainz: [], wikidata: ['alternative rock'] }, appleGenres: { Anime: 1 } },
      Peer: { method: 'style', tags: { musicbrainz: ['alternative rock'], wikidata: [] }, appleGenres: {} },
    },
    tracks: [
      { id: '1', title: 'Theme', artist: 'Band', group: 'Rock', appleGenre: 'Anime', years: { 2023: 10 } },
      { id: '2', title: 'Live', artist: 'Band', group: 'Rock', years: { 2024: 5 } },
      { id: '3', title: 'B-side', artist: 'Peer', group: 'Rock', years: { 2024: 12 } },
    ],
  });
  const search = (term: string, year = '') => searchLibrary(buildSearchIndex(catalog), term, year);
  assert.deepEqual(search('アニメ').map(hit => [hit.item.id, hit.matchedGenre]), [['1', 'Anime']]);
  assert.deepEqual(search('Anime', '2024'), []);
  assert.deepEqual(search('alternative', '2023').map(hit => [hit.item.name, hit.matchedGenre]), [['Band', 'alternative rock']]);
  const band = catalog.artists.get('Band')!;
  assert.equal(band.style?.method, 'style');
  assert.equal(band.children[0].parent?.style, band.style);
  assert.deepEqual(band.style?.appleGenres, { Anime: 1 });
  assert.equal(band.children[0].parent?.parent?.name, 'Rock');
  assert.deepEqual(catalog.neighbors.get('Peer')?.get('Band')?.tags, ['alternative rock']);
});
