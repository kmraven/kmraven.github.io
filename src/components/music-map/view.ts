import { amount, indexHistory, type ArtistStyle, type History, type Item, type Kind, type UnclassifiedReason } from './model';
import { buildSearchIndex, japaneseGenres, searchLibrary, type SearchHit } from './search';
import { mountArtistAtlas } from './atlas';

function el<K extends keyof HTMLElementTagNameMap>(tag: K, text = '', className = '') {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}
function action(text: string, fn: () => void, className = '') {
  const b = el('button', text, className);
  b.type = 'button';
  b.addEventListener('click', fn);
  return b;
}

export async function mountMusicMap(root: HTMLElement) {
  const ja = root.dataset.lang === 'ja';
  const pick = (j: string, e: string) => ja ? j : e;
  const get = <T extends HTMLElement = HTMLElement>(key: string) => root.querySelector<T>('[data-' + key + ']')!;
  const status = get('status');
  let history: History;
  try {
    const response = await fetch('/music/history.json');
    if (!response.ok) throw new Error(String(response.status));
    history = await response.json();
  } catch {
    status.replaceChildren(pick('再生履歴を読み込めませんでした。', 'Listening history could not be loaded. '),
      action(pick('再試行', 'Retry'), () => { status.textContent = pick('読み込み中…', 'Loading…'); void mountMusicMap(root); }));
    return;
  }
  const catalog = indexHistory(history);
  if (!catalog.tracks.length) {
    status.textContent = pick('再生履歴がありません。', 'No listening history is available.');
    return;
  }
  const canvas = get<HTMLCanvasElement>('atlas');
  const yearMenu = get<HTMLSelectElement>('year');
  const search = get<HTMLInputElement>('search');
  const list = get<HTMLUListElement>('list');
  const fmt = new Intl.NumberFormat(ja ? 'ja-JP' : 'en-US', { maximumFractionDigits: 1 });
  const fullNumber = new Intl.NumberFormat(ja ? 'ja-JP' : 'en-US');
  const time = (ms: number) => {
    if (ms >= 3600000) return fmt.format(ms / 3600000) + pick('時間', ' h');
    if (ms >= 60000) return fmt.format(ms / 60000) + pick('分', ' min');
    return fmt.format(ms / 1000) + pick('秒', ' s');
  };
  const pct = (ms: number, total: number) => ms > 0 && ms / total < .001 ? '<0.1%' : fmt.format(total ? ms * 100 / total : 0) + '%';
  const labels: Record<Kind, string> = { group: pick('ジャンル', 'Genres'), artist: pick('アーティスト', 'Artists'), track: pick('曲', 'Tracks') };
  const unknown: Record<Kind, string> = { group: pick('未分類', 'Unclassified'), artist: pick('アーティスト不明', 'Unknown artist'), track: pick('曲名不明', 'Unknown track') };
  const genreName = (group: string) => ja ? japaneseGenres[group] || group : group;
  const name = (item: Item) => {
    if (!item.name) return unknown[item.kind] + (item.kind === 'track' && item.id ? ' · ' + item.id : '');
    return item.kind === 'group' ? genreName(item.name) : item.name;
  };
  const favoriteLabel = pick('Apple Music のお気に入り', 'Apple Music favorite');
  function itemLabel(item: Item) {
    const label = el('span', name(item));
    if (item.favorite) {
      const star = el('span', '☆', 'mm-favorite');
      star.setAttribute('role', 'img');
      star.setAttribute('aria-label', favoriteLabel);
      star.title = favoriteLabel;
      label.append(star);
    }
    return label;
  }
  function itemHeading(item: Item) {
    const heading = el('h2');
    heading.append(itemLabel(item));
    return heading;
  }
  const inferredGroups = new Map(Object.entries(history.graphGroups ?? {}).filter(([, entry]) => entry.method === 'tags'));
  const unresolved = new Map(Object.entries(history.unclassifiedReasons ?? {}));
  const artistOf = (item?: Item) => item?.kind === 'track' ? item.parent : item?.kind === 'artist' ? item : undefined;
  const styleRelations = history.relation === 'style';
  const usesMusicBrainz = styleRelations || history.relation === 'musicbrainz';
  const appleGenreLabel = pick('Apple Music 配信ジャンル', 'Apple Music track genre');
  function sharedTags(a: Item, b: Item, tags: string[]) {
    const bySource = new Map<string, string[]>();
    for (const tag of tags) {
      const names = [];
      for (const [source, label] of [['musicbrainz', 'MusicBrainz'], ['wikidata', 'Wikidata'], ['official', pick('公式', 'Official')]] as const) {
        if (a.style?.tags[source]?.includes(tag) || b.style?.tags[source]?.includes(tag)) names.push(label);
      }
      const source = names.join(' / ');
      if (!bySource.has(source)) bySource.set(source, []);
      bySource.get(source)!.push(tag);
    }
    return [...bySource].map(([source, labels]) => labels.join(' · ') + (source ? ' (' + source + ')' : '')).join(' · ');
  }
  const reasons: Record<UnclassifiedReason, string> = {
    'credit-missing': pick('再生履歴にアーティスト名がなく、MusicBrainz と照合する名義を特定できませんでした。',
      'The listening history has no artist credit to match against MusicBrainz.'),
    'no-candidate': pick('今回の MusicBrainz 照合で、この名義に対応する候補が見つかりませんでした。',
      'The MusicBrainz lookup found no candidate for this credit.'),
    'identity-unverified': pick('MusicBrainz に候補はありましたが、この名義と同じアーティストか確認できませんでした。',
      'The MusicBrainz lookup found candidates but could not verify which artist this credit refers to.'),
    'no-genres': pick('照合した MusicBrainz の名義に、分類に使えるジャンルタグがありませんでした。',
      'The matched MusicBrainz artist had no usable genre tags.'),
    'genre-tie': pick('MusicBrainz のジャンルタグを集計すると複数の分類候補が同点になりました。',
      'MusicBrainz genre tags gave competing map genres equal support.'),
    'genre-unmapped': pick('MusicBrainz で有力なジャンルタグに、この地図の大分類に対応していないものがあり、所属を決められませんでした。',
      'Some of the strongest MusicBrainz genre tags have no equivalent among the genres on this map.'),
    'no-identity': pick('この名義に対応する MusicBrainz のアーティスト ID を確認できませんでした。',
      'A MusicBrainz artist ID could not be verified for this credit.'),
    'style-tie': pick('作風タグと曲の配信ジャンルでは、地図上の分類を一つに絞れませんでした。',
      'The style tags and track genres do not establish a single map genre.'),
  };
  function inferredLabel(item: Item) {
    const artist = artistOf(item);
    const placement = artist && inferredGroups.get(artist.name);
    return placement ? pick('推定ジャンル · ', 'Inferred genre · ') + genreName(placement.group) : '';
  }
  const searchIndex = buildSearchIndex(catalog, history.artistAliases);
  const allYears = pick('全期間', 'All years');
  const overview = pick('全ジャンル', 'All genres');
  const relationName = styleRelations ? pick('作風タグが似ているアーティスト', 'Artists with similar style tags')
    : usesMusicBrainz ? pick('MusicBrainz のジャンルタグが似ているアーティスト', 'Artists with similar MusicBrainz genre tags')
    : history.relation === 'apple' ? pick('Apple Music の類似アーティスト', 'Similar artists on Apple Music')
    : history.relation === 'genre' ? pick('曲のジャンル構成が近いアーティスト', 'Artists with similar track genre profiles') : '';
  let year = '';
  let path: Item[] = [];
  let listPage = 0;
  const listSize = 12;
  let atlas: ReturnType<typeof mountArtistAtlas>;
  const scope = () => path.filter(e => e.kind !== 'track').at(-1);
  const selection = () => path.at(-1);
  const directory = () => scope()?.children ?? catalog.groupList;
  function go(newPath: Item[], fromMap = false) {
    path = newPath;
    listPage = 0;
    search.value = '';
    render();
    atlas.focus(selection());
    if (fromMap) return;
    const nav = get(!path.length ? 'heading' : selection()?.kind === 'track' ? 'details' : 'path');
    nav.tabIndex = -1;
    nav.focus({ preventScroll: true });
    nav.scrollIntoView({ behavior: 'instant', block: 'nearest' });
  }
  function open(item: Item, fromMap = false) {
    const artist = scope();
    if (item.kind === 'track' && artist?.kind === 'artist' && artist.name === item.parent?.name) {
      go([...path.filter(x => x.kind !== 'track'), item], fromMap);
      return;
    }
    const chain = [item];
    for (let p = item.parent; p; p = p.parent) chain.unshift(p);
    go(chain, fromMap);
  }
  function renderPager(count: number) {
    const box = get('list-pager');
    const pages = Math.ceil(count / listSize);
    box.replaceChildren();
    box.hidden = pages < 2;
    if (box.hidden) return;
    for (const [direction, glyph] of [[-1, '‹'], [1, '›']] as const) {
      const b = action(glyph, () => {
        listPage += direction;
        renderList();
        const buttons = box.querySelectorAll<HTMLButtonElement>('button:not(:disabled)');
        (direction < 0 ? buttons[0] : buttons[buttons.length - 1])?.focus({ preventScroll: true });
      });
      b.setAttribute('aria-label', direction < 0 ? pick('前のページ', 'Previous page') : pick('次のページ', 'Next page'));
      b.disabled = listPage + direction < 0 || listPage + direction >= pages;
      box.append(b);
      if (direction < 0) box.append(el('span', (listPage + 1) + ' / ' + pages));
    }
  }
  function mountAtlas() {
    atlas?.destroy();
    atlas = mountArtistAtlas(canvas, catalog, year, item => name(item) + (item.favorite ? ' ☆' : ''), time, item => open(item, true), relationName, inferredLabel, sharedTags);
  }
  function renderStyle(panel: HTMLElement, artist: Item, style: ArtistStyle) {
    const group = artist.parent ?? artist.children[0]?.parent?.parent;
    const region = group ? name(group) : unknown.group;
    const details = el('dl');
    const field = (label: string, value: string | Node) => {
      const dd = el('dd');
      dd.append(value);
      details.append(el('dt', label), dd);
    };
    const neighbors = inferredGroups.get(artist.name)?.neighbors ?? [];
    const reason = unresolved.get(artist.name);
    const methods: Record<ArtistStyle['method'], string> = {
      style: pick('アーティストの作風タグに基づく分類', 'Based on the artist’s style tags'),
      'apple-tracks': pick('履歴にある曲の配信ジャンルに基づく分類', 'Based on the genres of tracks in this history'),
      export: pick('Apple Music のエクスポート情報に基づく分類', 'Based on metadata in the Apple Music export'),
      graph: pick('作風タグが似ている分類済みの名義から推定', 'Inferred from classified artists with similar style tags')
        + (neighbors.length ? ' (' + neighbors.join(ja ? '、' : ', ') + ')' : ''),
      unresolved: reason ? reasons[reason] : pick('分類に必要な情報が不足しています。', 'There is too little evidence to assign a map genre.'),
    };
    field(pick('地図上の分類', 'Map genre'), region + ' · ' + methods[style.method]);
    const sources = el('ul', '', 'mm-style-sources');
    for (const [source, label, href] of [
      ['musicbrainz', 'MusicBrainz', style.mbid && 'https://musicbrainz.org/artist/' + encodeURIComponent(style.mbid) + '/tags'],
      ['wikidata', 'Wikidata (P136)', style.qid && 'https://www.wikidata.org/wiki/' + encodeURIComponent(style.qid) + '#P136'],
      ['official', pick('公式プロフィール', 'Official profile'), style.officialUrl],
    ] as const) {
      const tags = style.tags[source] ?? [];
      if (!tags.length && !href) continue;
      const row = el('li');
      if (href && /^https?:\/\//i.test(href)) {
        const link = el('a', label);
        link.href = href;
        row.append(link);
      } else row.append(label);
      row.append(' · ', tags.length ? tags.join(' · ') : pick('タグなし', 'No tags'));
      sources.append(row);
    }
    field(pick('アーティストの作風タグ', 'Artist style tags'), sources.children.length ? sources : pick('出典を確認できたタグはありません。', 'No sourced style tags are available.'));
    if (style.workContext) {
      const context = pick(style.workContext.ja, style.workContext.en);
      if (style.officialUrl && /^https?:\/\//i.test(style.officialUrl)) {
        const link = el('a', context);
        link.href = style.officialUrl;
        field(pick('アーティストと関連作品', 'Artist’s connection to a work'), link);
      } else field(pick('アーティストと関連作品', 'Artist’s connection to a work'), context);
    }
    const genres = Object.entries(style.appleGenres).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    const tracks = catalog.artists.get(artist.name)!.children;
    const totalTracks = style.zeroDurationOnly ? tracks.length : tracks.filter(track => track.total > 0).length;
    const missing = totalTracks - genres.reduce((sum, [, count]) => sum + count, 0);
    const counts = genres.map(([g, n]) => g + ' ' + fullNumber.format(n) + pick('曲', n === 1 ? ' track' : ' tracks'));
    if (missing > 0) counts.push(pick('記録なし', 'Unlisted') + ' ' + fullNumber.format(missing) + pick('曲', missing === 1 ? ' track' : ' tracks'));
    const distribution = style.zeroDurationOnly
      ? pick('再生時間が0の曲の配信ジャンル（全期間）', 'Apple Music genres of zero-duration tracks · all years')
      : pick('聴いた曲の配信ジャンル（全期間）', 'Apple Music genres of tracks played · all years');
    field(distribution, counts.join(ja ? '、' : ' · '));
    panel.append(itemHeading(artist), details);
  }
  function renderGroupNote() {
    const panel = get('group-note');
    const selected = selection();
    const artist = artistOf(selected);
    panel.replaceChildren();
    panel.hidden = true;
    if (usesMusicBrainz && selected?.kind === 'group' && !selected.name) {
      const names = selected.children.filter(item => item.name && (!year || item.years[year] !== undefined));
      const linked = names.filter(item => catalog.neighbors.has(item.name)).length;
      panel.textContent = pick(
        'この期間の未分類のうち、アーティスト名がある' + fullNumber.format(names.length) + '組に対して、類似の線があるのは' + fullNumber.format(linked) + '組です。名義を選ぶと未分類の理由を確認できます。',
        'Of the ' + fullNumber.format(names.length) + ' named artists unclassified in this period, ' + fullNumber.format(linked) + ' have similarity links. Select an artist to see why their genre is unresolved.');
      panel.hidden = false;
      return;
    }
    if (!artist) return;
    if (artist.style) {
      renderStyle(panel, artist, artist.style);
      panel.hidden = false;
      return;
    }
    const placement = inferredGroups.get(artist.name);
    if (placement) {
      const seeds = placement.neighbors.join(ja ? '、' : ', ');
      panel.append(el('strong', inferredLabel(artist)), ' ',
        pick(artist.name + ' の配置は、MusicBrainz のジャンルタグが似ている名義を最大2段階たどり、分類済みの名義（' + seeds + '）を根拠に推定しました。',
          'This placement for ' + artist.name + ' is inferred from already classified artists (' + seeds + '), following up to two links based on similar MusicBrainz genre tags.'));
    } else {
      const reason = unresolved.get(artist.name);
      if (!reason) return;
      const unclassified = artist.parent ? !artist.parent.name : artist.children.every(track => !track.parent?.parent?.name);
      if (!unclassified) return;
      panel.append(el('strong', pick('未分類 · ', 'Unclassified · ') + name(artist)), ' ',
        pick('Apple Music の情報だけではジャンルを特定できませんでした。', 'Apple Music metadata did not establish a genre. '), reasons[reason]);
    }
    panel.hidden = false;
  }
  function renderTrack() {
    const item = selection();
    const panel = get('details');
    panel.hidden = item?.kind !== 'track';
    panel.replaceChildren();
    if (!item || panel.hidden) return;
    panel.append(itemHeading(item));
    if (item.titleAliases?.length) panel.append(el('p', item.titleAliases.join(' / ')));
    panel.append(el('p', (item.credit || name(item.parent!)) + ' · ' + (year || allYears) + ' · ' + time(amount(item, year))));
    panel.append(el('p', appleGenreLabel + ' · ' + (item.appleGenre || pick('記録なし', 'Unlisted'))));
    const bars = el('ul', '', 'mm-year-bars');
    bars.setAttribute('aria-label', pick('年ごとの再生時間', 'Listening time by year'));
    const maximum = Math.max(1, ...Object.values(item.years));
    for (const [y, ms] of Object.entries(item.years).sort()) {
      const li = el('li'), line = el('span', '', 'mm-bar');
      line.style.setProperty('--bar', ms / maximum * 100 + '%');
      li.append(el('span', y), line, el('span', time(ms)));
      bars.append(li);
    }
    panel.append(bars);
    const query = [item.credit || item.parent?.name, item.name].filter(Boolean).join(' ');
    if (query) {
      const link = el('a', pick('Apple Music でこの曲を検索 ↗', 'Search for this track on Apple Music ↗'));
      link.href = 'https://music.apple.com/' + (ja ? 'jp' : 'us') + '/search?term=' + encodeURIComponent(query);
      panel.append(link);
    }
  }
  function renderRelated() {
    const item = scope(), box = get('related');
    box.replaceChildren();
    box.hidden = true;
    if (item?.kind !== 'artist' || !relationName) return;
    const peers = catalog.neighbors.get(item.name);
    if (!peers?.size) return;
    box.hidden = false;
    box.append(el('h2', relationName + pick('（全期間）', ' · all years')));
    const links = el('ul', '', 'mm-peer-list');
    for (const [n, match] of [...peers].sort((a, b) => b[1].score - a[1].score || a[0].localeCompare(b[0]))) {
      const peer = catalog.artists.get(n)!;
      const li = el('li');
      const button = action('', () => open(peer));
      button.append(itemLabel(peer), ' ›');
      if (match.tags.length) button.append(el('small', pick('共通タグ · ', 'Shared tags · ') + sharedTags(item, peer, match.tags)));
      li.append(button);
      links.append(li);
    }
    box.append(links);
  }
  function renderList() {
    const q = search.value.trim();
    const parent = scope();
    const kind = !parent ? 'group' : parent.kind === 'group' ? 'artist' : 'track';
    const hits: SearchHit[] = q ? searchLibrary(searchIndex, q, year) : [];
    const results = q ? hits.map(hit => hit.item) : directory().filter(item => !year || item.years[year] !== undefined)
      .sort((a, b) => amount(b, year) - amount(a, year) || a.name.localeCompare(b.name));
    const panel = get('directory');
    const slot = get(q ? 'results-slot' : 'browse-slot');
    if (panel.parentElement !== slot) slot.append(panel);
    panel.classList.toggle('mm-search-results', Boolean(q));
    const base = amount(q ? catalog.totals : parent ?? catalog.totals, year);
    get('heading').textContent = q ? pick('検索結果', 'Search results') : labels[kind];
    const start = listPage * listSize;
    const end = Math.min(start + listSize, results.length);
    const count = fullNumber.format(results.length);
    get('count').textContent = results.length
      ? (year || allYears) + ' · ' + (ja ? count + '件中 ' + (start + 1) + '–' + end + '件' : (start + 1) + '–' + end + ' of ' + count)
      : pick('該当する項目はありません。', 'No matching items.');
    if (q && year && !results.length && searchLibrary(searchIndex, q, '').length) {
      get('count').replaceChildren(pick(year + '年の該当項目はありません。', 'No matches in ' + year + '. '),
        action(pick('全期間で検索', 'Search all years'), () => {
          yearMenu.value = '';
          yearMenu.dispatchEvent(new Event('change'));
          search.focus({preventScroll: true});
        }));
    }
    list.replaceChildren();
    list.scrollTop = 0;
    for (let i = start; i < end; i++) {
      const row = results[i];
      const li = el('li');
      const button = action('', () => {
        if (!q) { open(row); return; }
        open(row, true);
        canvas.focus({preventScroll: true});
        canvas.scrollIntoView({block: 'nearest', behavior: 'instant'});
      }, 'mm-row');
      const dot = el('span', '', 'mm-swatch');
      dot.style.color = 'var(--mm-color-' + (row.color % 8) + ')';
      const text = el('span', '', 'mm-row-text');
      const label = itemLabel(row);
      label.className = 'mm-row-name';
      text.append(label);
      if (q) {
        const typeLabel = row.kind === 'group' ? pick('ジャンル', 'Genre') : row.kind === 'artist' ? pick('アーティスト', 'Artist') : pick('曲', 'Track');
        const info = [typeLabel];
        if (hits[i].titleAlias) info.push(hits[i].titleAlias!);
        if (row.kind === 'track') info.push(row.credit || name(row.parent!));
        if (hits[i].alias && !info.includes(hits[i].alias!)) info.push(hits[i].alias!);
        if (hits[i].matchedGenre) info.push((row.kind === 'track' ? appleGenreLabel : pick('作風タグ', 'Style tag')) + ' · ' + hits[i].matchedGenre);
        const placement = inferredLabel(row);
        if (placement) info.push(placement);
        text.append(el('small', info.join(' · ')));
      } else if (row.kind === 'group') {
        const representatives = [...row.children].filter(item => amount(item, year)).sort((a, b) => amount(b, year) - amount(a, year)).slice(0, 3);
        if (representatives.length) text.append(el('small', representatives.map(name).join(' · ')));
      } else if (row.kind === 'artist' && inferredGroups.has(row.name)) {
        text.append(el('small', inferredLabel(row)));
      } else if (row.kind === 'track' && row.credit) {
        text.append(el('small', row.credit));
      }
      const value = el('span', '', 'mm-values');
      value.append(el('span', time(amount(row, year))), el('small', pct(amount(row, year), base)));
      const chevron = el('span', '›', 'mm-chevron');
      chevron.setAttribute('aria-hidden', 'true');
      button.append(dot, text, value, chevron);
      li.append(button);
      list.append(li);
    }
    renderPager(results.length);
  }
  function render() {
    const nav = get('path');
    nav.hidden = !path.length;
    nav.tabIndex = -1;
    nav.replaceChildren();
    const crumbs = [overview, ...path.map(name)];
    crumbs.forEach((label, i) => {
      if (i) nav.append(el('span', '›', 'mm-path-sep'));
      if (i === crumbs.length-1) nav.append(el('strong', label));
      else nav.append(action(label, () => go(path.slice(0, i))));
    });
    const n = year ? catalog.tracks.reduce((sum, t) => sum + Number(t.years[year] !== undefined), 0) : catalog.tracks.length;
    const dates = [history.start, history.end].filter(Boolean);
    get('totals').textContent = (!year && dates.length ? dates.join(' – ') + ' · ' : '') + time(amount(catalog.totals, year)) + ' · ' + fullNumber.format(n) + pick('曲', ' tracks');
    renderGroupNote();
    renderTrack();
    renderRelated();
    renderList();
  }

  yearMenu.add(new Option(allYears, ''));
  for (const y of catalog.years) yearMenu.add(new Option(y, y));
  yearMenu.addEventListener('change', () => { year = yearMenu.value; listPage = 0; mountAtlas(); render(); });
  const clearSearch = () => {
    search.value = '';
    listPage = 0;
    renderList();
    search.focus({preventScroll: true});
  };
  search.addEventListener('input', () => { listPage = 0; renderList(); });
  search.addEventListener('keydown', event => {
    if (event.isComposing || !search.value.trim()) return;
    const first = list.querySelector<HTMLButtonElement>('button');
    if (event.key === 'ArrowDown') first?.focus();
    else if (event.key === 'Enter') first?.click();
    else if (event.key === 'Escape') clearSearch();
    else return;
    event.preventDefault();
  });
  list.addEventListener('keydown', event => {
    if (!search.value.trim() || !(event.target instanceof HTMLButtonElement)) return;
    const li = event.target.closest('li')!;
    if (event.key === 'ArrowDown') li.nextElementSibling?.querySelector('button')?.focus();
    else if (event.key === 'ArrowUp') (li.previousElementSibling?.querySelector('button') ?? search).focus();
    else if (event.key === 'Escape') clearSearch();
    else return;
    event.preventDefault();
  });
  const legend = get('legend');
  legend.append(el('span', pick('円の面積は再生時間', 'Circle area shows listening time'), 'mm-size-key'));
  if (history.favorites?.artists.length || history.favorites?.tracks.length)
    legend.append(el('span', '☆ ' + favoriteLabel));
  if (history.tracks.some(track => track.credit)) {
    legend.append(el('span', pick('共演曲の再生時間は先頭のアーティストに集計', 'Joint tracks count toward the first credited artist')));
  }
  if (inferredGroups.size) {
    const count = fullNumber.format(inferredGroups.size);
    legend.append(el('span', pick('関連名義からジャンルを推定した名義 ' + count + ' 件', 'Genre inferred from related artists for ' + count + ' credits')));
  }
  if (relationName && catalog.neighbors.size) legend.append(el('span', relationName, 'mm-edge-key'));
  if (usesMusicBrainz) {
    const coverage = history.coverage?.musicbrainz;
    if (coverage) {
      const linked = fullNumber.format(coverage.linkedCredits);
      const total = fullNumber.format(coverage.totalCredits);
      legend.append(el('span', pick('全期間で ' + total + ' 名義中 ' + linked + ' 名義に類似関係', linked + ' of ' + total + ' artist credits linked across all years')));
    }
    const credit = el('p', '', 'mm-credit');
    const source = el('a', pick('MusicBrainz の投稿者', 'MusicBrainz contributors'));
    source.href = 'https://musicbrainz.org/doc/MusicBrainz_Database';
    const license = el('a', 'CC BY-NC-SA 3.0');
    license.href = 'https://creativecommons.org/licenses/by-nc-sa/3.0/';
    license.rel = 'license';
    if (styleRelations) {
      const wikidata = el('a', 'Wikidata');
      wikidata.href = 'https://www.wikidata.org/wiki/Property:P136';
      const cc0 = el('a', 'CC0');
      cc0.href = 'https://creativecommons.org/publicdomain/zero/1.0/';
      if (ja) {
        credit.append('線はアーティスト同士で共通する作風タグを示します。出典は ', source, '（', license, '）、', wikidata, ' のジャンル（', cc0, '）、各アーティストの公式資料です。');
      } else {
        credit.append('Lines connect artists who share style tags. Sources include ', source, ' (', license, '), ',
          wikidata, ' genres (', cc0, ') and official artist profiles.');
      }
    } else if (ja) {
      credit.append(source, 'によるジャンルタグを比較し、アーティスト間の線を生成しました。タグと派生した関係データは ', license, ' で利用できます。');
    } else {
      credit.append('Connections are calculated from genre tags supplied by ', source, '. The tags and derived connections are licensed under ', license, '.');
    }
    legend.after(credit);
    if (catalog.neighbors.size) {
      legend.append(el('span', pick('線に触れると共通タグを表示', 'Hover over or tap a line for shared tags')));
    }
  }
  get('view').hidden = false;
  status.hidden = true;
  mountAtlas();
  render();
}
