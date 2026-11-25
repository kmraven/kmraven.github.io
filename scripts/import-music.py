# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Build the public annual listening history from an Apple Music Activity export.

Usage: uv run scripts/import-music.py "/path/to/Apple Music Activity" [--musicbrainz-dir private/musicbrainz] [--watch]
Catalog format: {"tracks": {"songId": {"artist": "...", "artistId": "...", "title": "...",
"genre": "..."}}, "similar": {"artistId": ["otherArtistId"]}}.
"""

import argparse
import csv
import json
import sqlite3
import sys
import tarfile
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from fractions import Fraction
from itertools import combinations
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import BadZipFile, ZipFile

from musicbrainz_graph import musicbrainz_graph
from music_artists import apply_recorded_leads, assign_primary_artists, canonicalize
from music_genres import GENRE_INPUT_FILES, fallback_groups
from music_graph_groups import adjacency, predict, unclassified_reasons, validate
from music_genre_sources import GenreRefreshError


DAILY_FILE = "Apple Music - Play History Daily Tracks.csv"
CONTAINER_FILE = "Apple Music - Container Details.csv"
TRACK_LIBRARY = "Apple Music Library Tracks"
ARTIST_LIBRARY = "Apple Music Library Artists"
IDENTIFIER_INFO = "Identifier Information"
RECENT_TRACKS = "Apple Music - Recently Played Tracks.csv"
FAVORITES = "Apple Music - Favorites.csv"


GENRE_FAMILIES = {
    "J-Pop": ["Japanese Pop", "Kayokyoku", "歌謡曲"],
    "K-Pop": [],
    "Pop": ["Indie Pop", "Teen Pop", "Traditional Pop", "ポップ"],
    "Rock": ["ロック", "Alternative", "オルタナティブ", "Indie Rock", "Hard Rock", "Metal",
             "Heavy Metal", "Death Metal/Black Metal", "EMO", "Pop/Rock", "Punk", "College Rock",
             "Arena Rock", "Prog-Rock/Art Rock"],
    "Dance / Electronic": ["Dance", "Electronic", "Electronica", "House", "Techno",
                           "Downtempo", "Ambient", "ダンス", "エレクトロニック"],
    "Hip-Hop / Rap": ["Hip Hop/Rap", "Hip-Hop/Rap", "Hip-Hop", "Rap", "Alternative Rap",
                      "Underground Rap", "ヒップホップ／ラップ"],
    "R&B / Soul": ["R&B/Soul", "Soul", "Neo-Soul", "Contemporary R&B", "Funk"],
    "Jazz": ["ジャズ", "Fusion", "Contemporary Jazz", "Crossover Jazz", "Mainstream Jazz",
             "Smooth Jazz", "Big Band"],
    "Classical": ["クラシック", "Orchestral", "Chamber Music", "Classical Crossover"],
    "Anime / Soundtrack": ["Anime", "アニメ", "Soundtrack", "サウンドトラック"],
    "World": ["Worldwide", "ワールド"],
    "Spoken Audio": ["Spoken & Audio", "Spoken Word"],
}


def clean(value):
    value = unicodedata.normalize("NFC", str(value or "").strip())
    return "" if value.casefold() in {"n/a", "unknown", "null"} else value


def key(value):
    return unicodedata.normalize("NFKC", clean(value)).casefold()


FAMILY_BY_GENRE = {key(label): group for group, labels in GENRE_FAMILIES.items()
                   for label in [group, *labels]}


def group_of(genre):
    if key(genre) in {"", "music", "other", "unclassifiable", "その他"}:
        return ""
    return FAMILY_BY_GENRE.get(key(genre), clean(genre))


def sole(values):
    values = set(values) - {""}
    return values.pop() if len(values) == 1 else ""


def csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source, strict=True):
            if None in row.values() or None in row:
                raise ValueError(f"Incomplete or malformed row in {path.name}")
            yield row


def metadata_rows(folder, name):
    path = folder / f"{name}.json.zip"
    if path.exists():
        with ZipFile(path) as archive, archive.open(f"{name}.json") as source:
            yield from json.load(source)


def map_favorites(preferences, rows, aliases, profiles, candidates, library_ids):
    """Map the latest explicit likes to existing track and canonical artist nodes."""
    tracks = {row["id"] for row in rows}
    artists = {row["artist"] for row in rows if row["artist"]}
    by_name = defaultdict(set)
    by_id = defaultdict(set)
    known_ids = {}
    for artist in artists:
        profile = profiles.get(artist, {})
        ids = set(candidates.get(profile.get("mbid"), {}).get("apple", ()))
        for name in [artist, *aliases.get(artist, ())]:
            by_name[key(name)].add(artist)
            ids.update(library_ids.get(key(name), ()))
        known_ids[artist] = ids
        for identifier in ids:
            by_id[identifier].add(artist)
    songs, acts = set(), set()
    for (kind, identifier), (_, preference, name) in preferences.items():
        if preference != "LIKE":
            continue
        if kind in {"Song", "Music Video"} and identifier in tracks:
            songs.add(identifier)
        elif kind == "Artist":
            matches = by_id.get(identifier) or {a for a in by_name[key(name)] if not known_ids[a]}
            if len(matches) == 1:
                acts.update(matches)
    return {"tracks": sorted(songs), "artists": sorted(acts)}


def genre_edges(profiles, identities):
    supported = {artist: counts for artist, counts in profiles.items()
                 if len(counts) >= 2 and counts.total() >= 3}
    squared_norms = {artist: sum(count ** 2 for count in counts.values())
                     for artist, counts in supported.items()}
    neighbors = defaultdict(list)
    for (a, left), (b, right) in combinations(supported.items(), 2):
        if identities[a] & identities[b]:
            continue
        shared = left.keys() & right.keys()
        if len(shared) < 2:
            continue
        dot = sum(left[g] * right[g] for g in shared)
        # Squaring preserves the ranking of nonnegative cosine scores and exact ties.
        score_squared = Fraction(dot ** 2, squared_norms[a] * squared_norms[b])
        if score_squared >= Fraction(16, 25):
            neighbors[a].append((-score_squared, -len(shared), b))
            neighbors[b].append((-score_squared, -len(shared), a))
    top = {a: {b for _, _, b in sorted(ranks)[:3]} for a, ranks in neighbors.items()}
    edges = sorted((a, b) for a, names in top.items() for b in names if a < b and a in top[b])
    print(f"{len(supported):,} artist credits have enough song-level genre data; "
          f"{len({artist for pair in edges for artist in pair}):,} appear in genre edges")
    return edges


def build(folder, catalog, musicbrainz=None, musicbrainz_dir=None, genre_sources=None, update_genres=False):
    years = defaultdict(Counter)
    labels = defaultdict(Counter)
    source_totals = Counter()
    days = set()
    for row in csv_rows(folder / DAILY_FILE):
        if row["Media type"] != "AUDIO":
            continue
        track = row["Track Identifier"].strip()
        if not track:
            raise ValueError("Missing track identifier in an AUDIO row")
        day = date.fromisoformat(row["Date Played"])
        days.add(day)
        year = str(day.year)
        ms = int(row["Play Duration Milliseconds"])
        years[track][year] += ms
        source_totals[year] += ms
        description = clean(row["Track Description"])
        artist, separator, title = description.partition(" - ")
        credit = (clean(artist), clean(title)) if separator else ("", description)
        labels[track][credit] += ms
    if not days:
        raise ValueError("The daily history contains no AUDIO rows")

    artist_ids = defaultdict(set)
    for artist in metadata_rows(folder, ARTIST_LIBRARY):
        aid = clean(artist.get("Catalog Identifiers - Artist"))
        if aid.isdigit() and int(aid) > 1:
            artist_ids[key(artist.get("Artist Name"))].add(aid)

    # Each artist/title pair casts one vote, even when several library copies exist.
    song_groups = defaultdict(lambda: defaultdict(set))
    matches = defaultdict(list)
    for song in metadata_rows(folder, TRACK_LIBRARY):
        artist, title, group = clean(song.get("Artist")), clean(song.get("Title")), group_of(song.get("Genre"))
        if artist and title and group:
            song_groups[artist][key(title)].add(group)
        for field in ("Apple Music Track Identifier", "Purchased Track Identifier",
                      "Audio Matched Track Identifier", "Tag Matched Track Identifier"):
            track = clean(song.get(field))
            if track in years:
                matches[track].append((artist, title, group))

    title_variants = defaultdict(set)
    preferences = {}
    for entry in metadata_rows(folder, IDENTIFIER_INFO):
        track = clean(entry.get("Identifier"))
        if track in years:
            title_variants[track].add(clean(entry.get("Title")))
    for filename, kind, value, ref, description in (
        (RECENT_TRACKS, "Media type", "AUDIO", "Track Reference", "Track Description"),
        (FAVORITES, "Favorite Type", "Song", "Item Reference", "Item Description"),
    ):
        if (folder / filename).exists():
            for row in csv_rows(folder / filename):
                track = clean(row[ref])
                if filename == FAVORITES and track and row.get("Preference"):
                    identity = (row[kind], track)
                    stamp = row.get("Last Modified", "")
                    if identity not in preferences or stamp >= preferences[identity][0]:
                        preferences[identity] = (stamp, row["Preference"], row[description])
                if track in years and row[kind] == value:
                    _, separator, alternate = clean(row[description]).partition(" - ")
                    if separator:
                        title_variants[track].add(clean(alternate))

    container_votes = defaultdict(set)
    container_file = folder / CONTAINER_FILE
    for row in csv_rows(container_file) if container_file.exists() else ():
        # These rows list genres and artists for the played contents. Only a single
        # credited artist and a single substantive genre family identify a group.
        artist = clean(row["Artists"])
        if not artist or ", " in artist:
            continue
        groups = set(map(group_of, row["Genres"].split(","))) - {""}
        if groups in ({"J-Pop", "Pop"}, {"K-Pop", "Pop"}):
            groups.remove("Pop")
        if len(groups) == 1:
            container_votes[artist].add((row["Container Description"], groups.pop()))

    exact_groups = {}
    catalog_ids = defaultdict(set)
    identities = defaultdict(set)
    output = []
    for track in sorted(years):
        external = catalog.get("tracks", {}).get(track, {})
        artist, title = max(labels[track], key=lambda x: (bool(x[0]), labels[track][x], x))
        local = matches.get(track, [])
        artist = artist or clean(external.get("artist")) or sole(a for a, _, _ in local)
        variants = title_variants[track]
        variants.update(t for _, t in labels[track])
        variants.update(t for _, t, _ in local)
        variants.add(clean(external.get("title")))
        variants.discard("")
        title = title or clean(external.get("title")) or sole(t for _, t, _ in local) or sole(variants)
        group = group_of(external.get("genre")) or sole(g for _, _, g in local)
        exact_groups[track] = group
        if artist:
            if title and group:
                song_groups[artist][key(title)].add(group)
            names = {key(artist), key(external.get("artist")), sole(key(a) for a, _, _ in local)} - {""}
            for name in names:
                identities[artist].add(("name", name))
                identities[artist].update(("id", identifier) for identifier in artist_ids[name])
            aid = clean(external.get("artistId"))
            if aid.isdigit() and int(aid) > 1:
                catalog_ids[artist].add(aid)
                identities[artist].add(("id", aid))
        output.append({"id": track, "title": title, "artist": artist, "group": "",
                       "years": dict(sorted(years[track].items()))})
        alternate_titles = {key(t): t for t in sorted(variants) if key(t) != key(title)}
        if alternate_titles:
            output[-1]["titleAliases"] = sorted(alternate_titles.values())

    def dominant(votes):
        ranked = votes.most_common(2)
        if ranked and (len(ranked) == 1 or ranked[0][1] > ranked[1][1]):
            return ranked[0][0]
        return ""

    artist_groups = {}
    profiles = {}
    for artist in identities:
        counts = Counter(sole(groups) for groups in song_groups[artist].values())
        counts.pop("", None)
        profiles[artist] = counts
        artist_groups[artist] = dominant(counts) or dominant(Counter(g for _, g in container_votes[artist]))

    covered = Counter()
    covered_ms = Counter()
    if musicbrainz_dir:
        from musicbrainz_match import apple_ids, match
        from musicbrainz_recordings import recording_index

        history = {"tracks": output}
        recordings = recording_index(musicbrainz_dir / "canonical.tar.zst", history,
                                     musicbrainz_dir / "recordings.sqlite")
        musicbrainz = match(musicbrainz_dir / "artist.tar.xz", folder, history, recordings,
                            musicbrainz_dir / "matches.json", lead_catalog=catalog.get("tracks", {}))
    else:
        cached = musicbrainz or {}
        assign_primary_artists(output, cached.get("artists", {}), catalog.get("tracks", {}),
                               cached.get("knownArtistNames", ()), cached.get("possibleMemberNames", ()))
        apply_recorded_leads(output, cached.get("recordingLeads", {}))
    for record in output:
        record["group"] = artist_groups.get(record["artist"], "") or exact_groups[record["id"]]
    coverage = {}
    aliases = {}
    styles = {}
    candidates = None
    identifiers = None
    if musicbrainz_dir:
        candidates = json.loads((musicbrainz_dir / "candidates.json").read_text())["artists"]
        identifiers = apple_ids(folder)
    if musicbrainz is not None:
        musicbrainz, aliases = canonicalize(output, musicbrainz)
    apple = {row["artist"]: row["group"] for row in output if row["artist"] and row["group"]}
    fallback = fallback_groups(output, musicbrainz or {"artists": {}}, folder)
    profiles_for_edges = musicbrainz
    if genre_sources is not None:
        from music_styles import OFFICIAL_MBIDS, apply_styles

        matched = dict(musicbrainz or {"artists": {}})
        matched["profilesByMbid"] = {mbid: candidates[mbid] for mbid in OFFICIAL_MBIDS
                                     if candidates and mbid in candidates}
        if update_genres:
            from music_genre_sources import refresh_sources

            mbids = {entry["mbid"] for entry in matched["artists"].values()} | set(OFFICIAL_MBIDS)
            source_cache = refresh_sources(genre_sources, years.keys(), mbids)
        else:
            source_cache = json.loads(genre_sources.read_text(encoding="utf-8"))
        styles, profiles_for_edges = apply_styles(output, matched, source_cache, group_of, {**fallback, **apple})
        for name, detail in styles.items():
            profile = matched["profilesByMbid"].get(detail.get("mbid"), {})
            extra_names = set(profile.get("aliases", ())) - {name}
            if extra_names:
                aliases[name] = sorted(extra_names.union(aliases.get(name, ())))
        # Placement now accounts for all direct evidence, including the older export labels.
        fallback = {}
    if profiles_for_edges is not None:
        credit_ms = Counter()
        for record in output:
            credit_ms[record["artist"]] += sum(record["years"].values())
        edges, stats = musicbrainz_graph(profiles_for_edges, credit_ms)
        coverage["musicbrainz"] = stats
        relation = "style" if genre_sources is not None else "musicbrainz"
        for stage in ("matched", "tagged", "linked"):
            print(f"{relation} {stage}: {stats[f'{stage}Credits']:,}/{stats['totalCredits']:,} "
                  f"artist credits, {stats[f'{stage}Ms'] / 3_600_000:,.2f}/"
                  f"{stats['totalMs'] / 3_600_000:,.2f} hours")
    else:
        by_artist_id = defaultdict(set)
        for record in output:
            artist = record["artist"]
            apple = catalog.get("tracks", {}).get(record["id"], {})
            aid = clean(apple.get("artistId"))
            if not aid or record.get("credit") and clean(apple.get("artist")) != artist:
                aid = sole(catalog_ids[artist] or artist_ids[key(artist)])
            if aid.isdigit() and int(aid) > 1 and artist:
                by_artist_id[aid].add(artist)
        by_id = {aid: sole(names) for aid, names in by_artist_id.items()}
        edges = set()
        for aid, related in catalog.get("similar", {}).items():
            a = by_id.get(aid)
            for target in related:
                b = by_id.get(str(target))
                if a and b and a != b and not identities[a] & identities[b]:
                    edges.add(tuple(sorted((a, b))))
        relation = "apple" if edges else "genre"
        edges = sorted(edges) if edges else genre_edges(profiles, identities)
        active = {row["artist"] for row in output}
        edges = [(a, b) for a, b in edges if a in active and b in active]
        if not edges:
            relation = "none"
    matches_by_name = (profiles_for_edges or {}).get("artists", {})
    unknown = {row["artist"] for row in output if not row["group"]} - fallback.keys()
    graph_groups = {}
    reasons = {}
    if relation in {"musicbrainz", "style"}:
        seeds = {**fallback, **{row["artist"]: row["group"] for row in output if row["artist"] and row["group"]}}
        neighbors = adjacency(edges)
        for artist in sorted(unknown - seeds.keys()):
            result = predict(artist, neighbors, seeds)
            if result:
                graph_groups[artist] = result
                if artist in styles:
                    styles[artist]["method"] = "graph"
        scores = validate(neighbors, seeds, seeds)
        def agreement(labels):
            evaluated = [(guess, labels[artist]) for artist, guess, _ in scores if artist in labels]
            return {"eligible": len(labels), "predicted": len(evaluated),
                    "agreed": sum(guess == label for guess, label in evaluated)}
        coverage["graphHoldout"] = {"all": agreement(seeds), "apple": agreement(apple)}
        reasons = unclassified_reasons(sorted(unknown - graph_groups.keys()), matches_by_name, candidates, identifiers)
        for artist in reasons.keys() & styles.keys():
            if styles[artist]["appleGenres"] or any(styles[artist]["tags"].values()):
                reasons[artist] = "style-tie"
    totals = Counter()
    for record in output:
        track = record["id"]
        artist = record["artist"]
        group = record["group"]
        if group and artist in styles:
            source = styles[artist]["method"]
        elif group:
            source = "track-confirmed" if group == exact_groups[track] else "artist-inferred"
        elif artist in fallback:
            record["group"] = fallback[artist]
            source = "catalog-or-export"
        elif artist in graph_groups:
            record["group"] = graph_groups[artist]["group"]
            source = "graph-inferred"
        else:
            source = "unresolved"
        covered[source] += 1
        covered_ms[source] += sum(record["years"].values())
        totals.update(record["years"])
    if dict(totals) != dict(source_totals) or len(output) != len(years):
        raise ValueError("Annual durations or track count differ from source")
    print(f"{len(output):,} tracks, {len(identities):,} credited artist names, "
          f"{sum(totals.values()):,} ms, {len(edges):,} {relation} edges")
    print("Genre coverage (track count / hours):", ", ".join(
        f"{s} {covered[s]:,} / {covered_ms[s] / 3_600_000:,.2f}" for s in sorted(covered)))
    data = {"start": min(days).isoformat(), "end": max(days).isoformat(), "tracks": output,
            "edges": edges, "relation": relation}
    if aliases:
        data["artistAliases"] = aliases
    if preferences:
        data["favorites"] = map_favorites(preferences, output, aliases, matches_by_name, candidates or {}, artist_ids)
    if genre_sources is not None:
        data["artistStyles"] = styles
        coverage["styles"] = {
            "appleGenreTracks": sum(bool(row.get("appleGenre")) for row in output),
            "placements": dict(Counter(entry["method"] for entry in styles.values())),
        }
    if graph_groups:
        data["graphGroups"] = graph_groups
    if reasons:
        data["unclassifiedReasons"] = reasons
    if coverage:
        data["coverage"] = coverage
        data["edgeAttribution"] = {
            "source": "MusicBrainz contributors",
            "url": "https://musicbrainz.org/doc/Development/JSON_Data_Dumps",
            "license": "https://creativecommons.org/licenses/by-nc-sa/3.0/",
            "modification": "Artist genre votes grouped into families and used for TF-IDF cosine similarities and neighborhood genre inference",
        }
        if relation == "style":
            data["edgeAttribution"].update({
                "additionalSources": ["https://www.wikidata.org/wiki/Property:P136",
                                      *sorted({item["officialUrl"] for item in styles.values() if item.get("officialUrl")})],
                "modification": "MusicBrainz votes, Wikidata genre statements and cited artist styles normalized and compared by TF-IDF cosine similarity",
            })
    return data


def source_state(paths):
    state = {}
    for path in paths:
        try:
            stat = path.stat()
        except FileNotFoundError:
            state[path] = None
        else:
            state[path] = (stat.st_size, stat.st_mtime_ns)
    return state


def export(args, expected=None):
    catalog = json.loads(args.catalog.read_text(encoding="utf-8")) if args.catalog else {}
    musicbrainz = json.loads(args.musicbrainz.read_text(encoding="utf-8")) if args.musicbrainz else None
    data = build(args.folder, catalog, musicbrainz, args.musicbrainz_dir, args.genre_sources, args.update_genres)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.output.parent, delete=False)
    temp_path = Path(temp.name)
    try:
        with temp:
            json.dump(data, temp, ensure_ascii=False, separators=(",", ":"))
            temp.write("\n")
        if expected is not None and source_state(expected) != expected:
            raise ValueError("Input changed during import")
        temp_path.chmod(0o644)
        temp_path.replace(args.output)
    finally:
        temp_path.unlink(missing_ok=True)


def watch(args, interval=2):
    paths = [args.folder / name for name in
             (DAILY_FILE, *GENRE_INPUT_FILES, RECENT_TRACKS, FAVORITES, f"{IDENTIFIER_INFO}.json.zip",
              f"{ARTIST_LIBRARY}.json.zip", f"{TRACK_LIBRARY}.json.zip")]
    required = {args.folder / DAILY_FILE}
    if args.musicbrainz_dir:
        archives = [args.musicbrainz_dir / name for name in ("canonical.tar.zst", "artist.tar.xz")]
        paths.extend(archives)
        required.update(archives)
    for cache in (args.catalog, args.musicbrainz, args.genre_sources if not args.update_genres else None):
        if cache:
            paths.append(cache)
            required.add(cache)
    previous = None
    published = None
    last_error = None
    retry_at = 0
    while True:
        try:
            current = source_state(paths)
            if current == previous and current != published and time.time() >= retry_at:
                # An optional file that has already contributed to a published export
                # may briefly disappear during replacement. Wait for it to return.
                missing = [p.name for p in required if current[p] is None]
                if missing:
                    raise ValueError(f"Waiting for {', '.join(sorted(missing))}")
                export(args, expected=current)
                published = current
                required.update(p for p, stat in current.items() if stat is not None)
                last_error = None
                print(f"Updated {args.output}", flush=True)
            previous = current
        except (OSError, EOFError, ValueError, KeyError, AttributeError, TypeError, BadZipFile, csv.Error,
                sqlite3.Error, tarfile.TarError) as exc:
            if isinstance(exc, GenreRefreshError):
                retry_at = exc.retry_at
            if str(exc) != last_error:
                print(f"Import deferred: {exc}", file=sys.stderr, flush=True)
                last_error = str(exc)
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--genre-sources", type=Path, help="Apple song genres and Wikidata artist styles cache")
    parser.add_argument("--update-genres", action="store_true", help="look up missing public IDs when importing")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--musicbrainz", type=Path, help="derive similarities from a matched artist genre cache")
    source.add_argument("--musicbrainz-dir", type=Path, help="match every credit against local MusicBrainz snapshots")
    parser.add_argument("--watch", action="store_true", help="rebuild when stable export inputs change")
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parents[1] / "public/music/history.json")
    args = parser.parse_args()
    if args.update_genres and args.genre_sources is None:
        parser.error("--update-genres requires --genre-sources PATH")
    if args.watch:
        try:
            watch(args)
        except KeyboardInterrupt:
            pass
    else:
        export(args)


if __name__ == "__main__":
    main()
