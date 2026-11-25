export type Kind = 'group' | 'artist' | 'track';
export type YearTotals = Record<string, number>;
export type UnclassifiedReason = 'credit-missing' | 'no-candidate' | 'identity-unverified' | 'no-genres' | 'genre-tie' | 'genre-unmapped' | 'no-identity' | 'style-tie';
export interface ArtistStyle {
  method: 'style' | 'apple-tracks' | 'export' | 'unresolved' | 'graph';
  tags: { musicbrainz: string[]; wikidata: string[]; official?: string[] };
  appleGenres: Record<string, number>;
  mbid?: string;
  qid?: string;
  officialUrl?: string;
  workContext?: { ja: string; en: string };
  zeroDurationOnly?: boolean;
}
export interface History {
  start: string;
  end: string;
  tracks: { id: string; title: string; titleAliases?: string[]; artist: string; credit?: string; group: string; appleGenre?: string; years: YearTotals }[];
  artistStyles?: Record<string, ArtistStyle>;
  graphGroups?: Record<string, { group: string; neighbors: string[]; method: 'tags' }>;
  unclassifiedReasons?: Record<string, UnclassifiedReason>;
  artistAliases?: Record<string, string[]>;
  favorites?: { artists: string[]; tracks: string[] };
  edges: [string, string, string[]?, number?][];
  relation: 'musicbrainz' | 'style' | 'apple' | 'genre' | 'none';
  coverage?: { musicbrainz?: { linkedCredits: number; totalCredits: number } };
}
export interface Similarity {
  tags: string[];
  score: number;
}
export interface Item {
  kind: Kind;
  name: string;
  total: number;
  years: YearTotals;
  children: Item[];
  parent?: Item;
  color: number;
  id?: string;
  credit?: string;
  titleAliases?: string[];
  appleGenre?: string;
  style?: ArtistStyle;
  favorite?: boolean;
}
export const amount = (item: Pick<Item, 'total' | 'years'>, year: string) => year ? item.years[year] || 0 : item.total;
export function indexHistory(data: History) {
  const favoriteArtists = new Set(data.favorites?.artists);
  const favoriteTracks = new Set(data.favorites?.tracks);
  const item = (kind: Kind, name: string, parent?: Item): Item => ({
    kind, name, parent, total: 0, years: {}, children: [], color: 0,
  });
  const groups = new Map<string, Item>();
  const scopedArtists = new Map<Item, Map<string, Item>>();
  const artists = new Map<string, Item>();
  const tracks: Item[] = [];
  const totals = { total: 0, years: {} as YearTotals };
  for (const row of data.tracks) {
    let group = groups.get(row.group);
    if (!group) {
      group = item('group', row.group);
      groups.set(row.group, group);
      scopedArtists.set(group, new Map());
    }
    const byName = scopedArtists.get(group)!;
    let scoped = byName.get(row.artist);
    if (!scoped) {
      scoped = item('artist', row.artist, group);
      scoped.favorite = favoriteArtists.has(row.artist);
      scoped.style = data.artistStyles && Object.hasOwn(data.artistStyles, row.artist) ? data.artistStyles[row.artist] : undefined;
      byName.set(row.artist, scoped);
      group.children.push(scoped);
    }
    let artist = artists.get(row.artist);
    if (!artist) {
      artist = item('artist', row.artist);
      artist.favorite = scoped.favorite;
      artist.style = scoped.style;
      artists.set(row.artist, artist);
    }
    const track = item('track', row.title, scoped);
    track.id = String(row.id);
    track.favorite = favoriteTracks.has(track.id);
    track.credit = row.credit;
    track.titleAliases = row.titleAliases;
    track.appleGenre = row.appleGenre;
    for (const [year, ms] of Object.entries(row.years)) {
      if (!Number.isFinite(ms) || ms < 0) continue;
      for (const entry of [track, scoped, artist, group, totals]) {
        entry.total += ms;
        entry.years[year] = (entry.years[year] || 0) + ms;
      }
    }
    scoped.children.push(track);
    artist.children.push(track);
    tracks.push(track);
  }
  const ranked = (a: Item, b: Item) => b.total - a.total || a.name.localeCompare(b.name);
  const groupList = [...groups.values()].sort(ranked);
  for (const [color, group] of groupList.entries()) {
    group.color = color;
    group.children.sort(ranked);
    for (const artist of group.children) {
      artist.color = color;
      artist.children.sort(ranked);
      for (const track of artist.children) track.color = color;
    }
  }
  for (const artist of artists.values()) {
    artist.children.sort(ranked);
    artist.color = artist.children[0]?.color ?? 0;
  }
  const neighbors = new Map<string, Map<string, Similarity>>();
  if (data.relation !== 'none') {
    for (const [a, b, tags, score] of data.edges) {
      if (a === b || !artists.has(a) || !artists.has(b)) continue;
      const similarity = { tags: tags ?? [], score: score ?? 0 };
      for (const [from, to] of [[a, b], [b, a]]) {
        if (!neighbors.has(from)) neighbors.set(from, new Map());
        neighbors.get(from)!.set(to, similarity);
      }
    }
  }
  return { groupList, artists, tracks, totals, neighbors, years: Object.keys(totals.years).sort() };
}
export type Catalog = ReturnType<typeof indexHistory>;
