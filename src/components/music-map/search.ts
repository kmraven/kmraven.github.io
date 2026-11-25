import { amount, type Catalog, type Item } from './model.ts';

export const japaneseGenres: Record<string, string> = {
  'Anime / Soundtrack': 'アニメ・サウンドトラック', Classical: 'クラシック', 'Dance / Electronic': 'ダンス・電子音楽',
  'Hip-Hop / Rap': 'ヒップホップ・ラップ', Instrumental: 'インストゥルメンタル', Jazz: 'ジャズ', Latin: 'ラテン',
  Blues: 'ブルース', Country: 'カントリー', Folk: 'フォーク', 'New Age': 'ニューエイジ',
  Reggae: 'レゲエ', 'Singer/Songwriter': 'シンガーソングライター', 'Spoken Audio': 'スポークンワード',
  Pop: 'ポップ', 'R&B / Soul': 'R&B・ソウル', Rock: 'ロック', World: 'ワールド',
};
const otherGenreNames: Record<string, string[]> = {
  'J-Pop': ['Jポップ', 'ジェイポップ'], 'K-Pop': ['Kポップ', 'ケイポップ'],
  'Anime / Soundtrack': ['サントラ'], 'Dance / Electronic': ['エレクトロニック'],
};

function fold(text: string) {
  const normalized = text.normalize('NFKC').toLowerCase()
    .replace(/[ァ-ヶ]/g, ch => String.fromCharCode(ch.charCodeAt(0) - 0x60))
    .normalize('NFD').replace(/(\p{Script=Latin})\p{M}+/gu, '$1').normalize('NFC')
    .trim();
  return normalized.replace(/[\p{P}\p{S}\s]+/gu, ' ').trim() || normalized;
}

function fields(names: string[]) {
  const values = [...new Set(names)].map(text => {
    const value = fold(text);
    return { text, value, compact: value.replaceAll(' ', '') };
  }).filter(f => f.value);
  return { values, text: values.map(f => f.value + '\n' + f.compact).join('\n') };
}
type Fields = ReturnType<typeof fields>;
interface Entry {
  item: Item;
  own: Fields;
  artist?: Fields;
  credit?: Fields;
  genre?: Fields;
  metadata?: Fields;
}

export function buildSearchIndex(catalog: Catalog, aliases: Record<string, string[]> = {}) {
  const entries: Entry[] = [];
  const ids = new Map<string, Item>();
  const artistNames = new Map<string, Fields>();
  const artistGenres = new Map<string, string[]>();
  const appleGenres = new Map<string, Fields>();
  for (const artist of catalog.artists.values()) {
    const alternatives = Object.hasOwn(aliases, artist.name) ? aliases[artist.name] : [];
    artistNames.set(artist.name, fields(artist.name ? [artist.name, ...alternatives] : ['Unknown artist', 'アーティスト不明']));
  }
  for (const group of catalog.groupList) {
    const genres = group.name
      ? [group.name, japaneseGenres[group.name] ?? group.name, ...(otherGenreNames[group.name] ?? [])]
      : ['Unclassified', '未分類'];
    const genre = fields(genres);
    entries.push({ item: group, own: genre });
    for (const scoped of group.children) {
      const known = artistGenres.get(scoped.name);
      if (known) known.push(...genres);
      else artistGenres.set(scoped.name, [...genres]);
      const artist = artistNames.get(scoped.name)!;
      for (const track of scoped.children) {
        const titles = track.name ? [track.name] : ['Unknown track', '曲名不明'];
        const own = fields([...titles, ...(track.titleAliases ?? [])]);
        const credit = track.credit ? fields([track.credit]) : undefined;
        if (track.appleGenre && !appleGenres.has(track.appleGenre)) {
          const raw = track.appleGenre;
          const translation = raw === 'Anime' ? 'アニメ' : raw === 'Soundtrack' ? 'サウンドトラック' : japaneseGenres[raw];
          appleGenres.set(raw, fields([raw, ...(translation ? [translation] : []), ...(otherGenreNames[raw] ?? [])]));
        }
        entries.push({ item: track, own, artist, credit, genre, metadata: appleGenres.get(track.appleGenre ?? '') });
        if (track.id) ids.set(track.id, track);
      }
    }
  }
  for (const artist of catalog.artists.values()) {
    const metadata = artist.style ? fields(Object.values(artist.style.tags).flat()) : undefined;
    entries.push({ item: artist, own: artistNames.get(artist.name)!, genre: fields(artistGenres.get(artist.name)!), metadata });
  }
  return { entries, ids };
}

export interface SearchHit { item: Item; rank: number; alias?: string; titleAlias?: string; matchedGenre?: string }
export function searchLibrary(index: ReturnType<typeof buildSearchIndex>, input: string, year: string): SearchHit[] {
  const id = index.ids.get(input.normalize('NFKC').trim());
  if (id) return !year || id.years[year] !== undefined ? [{item: id, rank: 0}] : [];
  const query = fold(input);
  if (!query) return [];
  const tokens = query.split(' ');
  const compact = tokens.join('');
  const hits: SearchHit[] = [];
  for (const { item, own, artist, credit, genre, metadata } of index.entries) {
    if (year && item.years[year] === undefined) continue;
    if (!tokens.every(t => own.text.includes(t) || artist?.text.includes(t) || credit?.text.includes(t) || genre?.text.includes(t) || metadata?.text.includes(t))) continue;
    // Prefer an item's own name, then mixed title/artist queries, then context alone.
    let rank = 7;
    const exact = own.values.find(f => f.value === query || f.compact === compact);
    const prefix = !exact && own.values.find(f => f.value.startsWith(query) || f.compact.startsWith(compact));
    if (exact) {
      if (item.kind === 'track') rank = 2;
      else rank = item.kind === 'group' || exact === own.values[0] ? 0 : 1;
    } else if (prefix) rank = 3;
    else if (tokens.every(t => own.text.includes(t))) rank = 4;
    else if (tokens.some(t => own.text.includes(t))) rank = 5;
    else if (tokens.some(t => artist?.text.includes(t) || credit?.text.includes(t))) rank = 6;
    const names = item.kind === 'artist' ? own : artist;
    const canonical = names?.values[0];
    // Show the original alias when it contributed a term absent from the canonical name.
    const via = names?.values.find(f => tokens.some(t => f.compact.includes(t) && !canonical?.compact.includes(t)));
    const title = item.kind === 'track' && (exact || prefix || own.values.find(f =>
      tokens.some(t => f.compact.includes(t) && !own.values[0]?.compact.includes(t))));
    const titleAlias = title && item.titleAliases?.includes(title.text) ? title.text : undefined;
    const viaGenre = metadata?.values.find(f => tokens.some(t => f.compact.includes(t) && !own.text.includes(t)));
    hits.push({item, rank, alias: via?.text, titleAlias, matchedGenre: viaGenre && (item.appleGenre || viaGenre.text)});
  }
  return hits.sort((a, b) => a.rank - b.rank || amount(b.item, year) - amount(a.item, year)
    || a.item.name.localeCompare(b.item.name));
}
