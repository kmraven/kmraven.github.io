"""Assign artist families from verified styles while keeping Apple genres on individual works."""

from collections import Counter, defaultdict
import re

from music_genres import family_for, genre_key, norm, unique_winner


# This entity's MusicBrainz external links directly identify both the Apple artist
# https://music.apple.com/jp/artist/1688539273 and the Universal Music biography.
TOGENASHI_MBID = "d2beaa40-4a5f-44b7-a1c9-b12352bf4abf"
OFFICIAL_MBIDS = {TOGENASHI_MBID}
BIOGRAPHY = "https://www.universal-music.co.jp/togenashitogeari/biography/"

EMPTY_LABELS = {"", "music", "other", "unknown", "n/a", "null", "unclassifiable", "その他", "音楽"}
NON_STYLES = EMPTY_LABELS | {"popular music", "vocal music", "new music", "hip hop culture", "musician"}
ALIASES = {
    "j pop": "j-pop", "japanese pop": "j-pop", "k pop": "k-pop", "korean pop": "k-pop",
    "j rock": "j-rock", "japanese rock": "j-rock", "rhythm and blues": "r&b",
    "rhythm & blues": "r&b", "r and b": "r&b", "hiphop": "hip hop", "rapping": "rap",
    "electronic dance music": "edm", "intelligent dance music": "idm",
    "synthpop": "synth-pop", "synth pop": "synth-pop", "singer songwriter": "singer-songwriter",
    "contemporary singer songwriter music": "singer-songwriter", "regional mexican music": "regional mexicano",
    "edm trap music": "trap edm", "denpa song": "denpa", "anime song": "anime",
    "british hip hop": "uk hip hop", "american hip hop": "us hip hop",
    "british rap": "uk rap", "american rap": "us rap", "british drill": "uk drill",
    "drum & bass": "drum and bass", "synthesizer pop": "synth-pop", "synthesiser pop": "synth-pop",
}
EXTRA_FAMILIES = {"trap edm": "Dance / Electronic", "uk bass": "Dance / Electronic",
                  "anime": "Anime / Soundtrack", "video game music": "Anime / Soundtrack",
                  "musicals": "Anime / Soundtrack", "original score": "Anime / Soundtrack",
                  "tv soundtrack": "Anime / Soundtrack", "latin trap": "Latin", "música mexicana": "Latin"}
CONTEXTUAL = {"Anime / Soundtrack", "Singer/Songwriter", "Instrumental", "World"}
WORK_MEDIA = {"anime", "soundtrack", "tv soundtrack", "video game music", "アニメ", "サウンドトラック"}
BROAD_TAGS = {"rock", "j-rock", "pop", "j-pop", "k-pop", "dance", "electronic", "edm", "hip hop", "rap",
              "r&b", "soul", "jazz", "classical", "country", "folk", "reggae", "latin", "blues"}


def style_tag(label):
    tag = genre_key(label)
    if tag in NON_STYLES or re.fullmatch(r"q\d+", tag) or tag.startswith("music of "):
        return ""
    if tag in ALIASES:
        return ALIASES[tag]
    base = tag.removesuffix(" music")
    return base if family_for(base) else tag


def style_family(tag):
    return EXTRA_FAMILIES.get(tag) or family_for(tag)


def select_family(weights, tags, apple, legacy):
    """Sum each distinct style's strongest vote. Prefer corroboration, then specificity on ties."""
    votes = Counter()
    sources = defaultdict(set)
    specific = Counter()
    for tag, weight in weights.items():
        family = style_family(tag)
        if family:
            votes[family] += weight
            sources[family].update(source for source, labels in tags.items() if tag in labels)
            specific[family] += tag not in BROAD_TAGS
    # An artist's medium and role can coexist with evidence about how their music sounds.
    families = votes.keys() - CONTEXTUAL or votes.keys()
    if families:
        scores = {f: (votes[f], len(sources[f]), specific[f]) for f in families}
        best = max(scores.values())
        tied = {f for f in families if scores[f] == best}
        if len(tied) == 1:
            return tied.pop(), "style"
        corroborated = unique_winner(Counter({f: apple[f] for f in tied if apple[f]}))
        if corroborated:
            return corroborated, "style"
        return "", "unresolved"
    winner = unique_winner(apple)
    if winner:
        return winner, "apple-tracks"
    if not apple and legacy:
        return legacy, "export"
    return "", "unresolved"


def apply_styles(rows, matched, source_cache, group_of, legacy_groups):
    """Mutate rows and return provenance per canonical credit and profiles for musicbrainz_graph."""
    apple_tracks = source_cache.get("appleTracks", {})
    wikidata = source_cache.get("wikidataByMusicBrainzArtistId", {})
    by_artist = defaultdict(set)
    listened = defaultdict(set)
    genres = {}
    for row in rows:
        track = apple_tracks.get(row["id"], {})
        genre = (track.get("primaryGenreName") or "").strip()
        row.pop("appleGenre", None)
        if genre_key(genre) not in EMPTY_LABELS:
            row["appleGenre"] = genre
            genres[row["id"]] = genre
        if row["artist"]:
            by_artist[row["artist"]].add(row["id"])
            if "years" not in row or sum(row["years"].values()) > 0:
                listened[row["artist"]].add(row["id"])

    info, profiles, chosen = {}, {}, {}
    for artist, track_ids in sorted(by_artist.items()):
        counted = listened[artist] or track_ids
        raw = dict(sorted(Counter(genres[i] for i in counted if i in genres).items()))
        apple = Counter()
        for genre, count in raw.items():
            family = style_family(style_tag(genre)) or group_of(genre)
            if family:
                apple[family] += count

        profile = matched.get("artists", {}).get(artist, {})
        mbid = profile.get("mbid")
        artist_ids = {str(apple_tracks[i]["artistId"]) for i in track_ids if apple_tracks.get(i, {}).get("artistId")}
        if not mbid and artist_ids == {"1688539273"} and norm(artist) in {"togenashi togeari", "トゲナシトゲアリ"}:
            mbid = TOGENASHI_MBID
            profile = matched.get("profilesByMbid", {}).get(mbid, {})

        tags = {"musicbrainz": [], "wikidata": []}
        weights = Counter()
        detail = {"tags": tags, "appleGenres": raw}
        if not listened[artist]:
            detail["zeroDurationOnly"] = True
        if mbid:
            detail["mbid"] = mbid
            for label, count in profile.get("tags", {}).items():
                tag = style_tag(label)
                if tag and type(count) is int and count > 0:
                    weights[tag] = max(weights[tag], count)
            tags["musicbrainz"] = sorted(weights)
            entities = wikidata.get(mbid, {})
            if len(entities) == 1:
                qid, claims = next(iter(entities.items()))
                if re.fullmatch(r"Q[1-9]\d*", qid):
                    detail["qid"] = qid
                    tags["wikidata"] = sorted({style_tag(label) for label in claims.values()} - {""})
            if mbid == TOGENASHI_MBID:
                detail["officialUrl"] = BIOGRAPHY
                detail["workContext"] = {"ja": "アニメ「ガールズバンドクライ」の劇中バンド",
                                         "en": "The band featured in the anime Girls Band Cry"}
                tags["official"] = ["rock"]
            for tag in tags["wikidata"] + tags.get("official", []):
                weights[tag] = max(weights[tag], 1)
            # The same publishing medium alone says nothing about the musical sound.
            profiles[artist] = {"mbid": mbid, "tags": {t: weights[t] for t in sorted(weights.keys() - WORK_MEDIA)}}

        chosen[artist], detail["method"] = select_family(weights, tags, apple, legacy_groups.get(artist))
        info[artist] = detail
    for row in rows:
        row["group"] = chosen.get(row["artist"], "")
    return info, {"artists": profiles}
