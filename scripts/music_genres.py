"""Classify otherwise unresolved artist credits from local Apple and MusicBrainz metadata."""

import csv
from collections import Counter, defaultdict
import unicodedata


GENRE_INPUT_FILES = ("Apple Music - Container Details.csv", "Apple Music - Container Origin.csv")

# Genre aliases are explicit where a subgenre's name does not identify its family.
FAMILY_TERMS = {
    "J-Pop": "j pop|japanese pop|kayokyoku|kayōkyoku|city pop|shibuya kei|yakousei|idol kayō|歌謡曲",
    "K-Pop": "k pop|korean pop",
    "Pop": "pop|electropop|hyperpop|europop|britpop|mandopop|cantopop|c pop|synthpop",
    "Rock": ("rock|j rock|alternative|adult alternative|emo|grunge|shoegaze|metal|metalcore|"
             "post hardcore|melodic hardcore|visual kei|punk|screamo|rock and roll|rockabilly|"
             "new wave|krautrock|aor|djent|synth rock|post grunge|pop/rock|ロック|オルタナティブ"),
    "Dance / Electronic": ("dance|electronic|electronica|edm|idm|disco|nu disco|ambient|downtempo|"
                            "chillout|indietronica|techno|house|trance|dubstep|club|"
                            "drum and bass|jungle|garage|uk garage|2 step|breakbeat|breaks|"
                            "future bass|synthwave|chillwave|electro|trip hop|glitch|liquid funk|"
                            "footwork|eurobeat|eurodance|chiptune|amapiano|ダンス"),
    "Hip-Hop / Rap": ("hip hop|hip hop/rap|rap|trap|grime|drill|crunk|boom bap|"
                      "horrorcore|g funk|plugg|hiplife|dirty south"),
    "R&B / Soul": ("r&b|r&b/soul|rhythm and blues|soul|funk|motown|quiet storm|new jack swing|"
                   "doo wop|boogie|neo soul|hip hop soul"),
    "Jazz": ("jazz|jazz fusion|fusion|swing|bebop|post bop|hard bop|dixieland|big band|"
             "jazz funk|ジャズ"),
    "Classical": "classical|orchestral|opera|symphony|chamber music|string quartet|classical crossover|クラシック",
    "Anime / Soundtrack": "anime|soundtrack|film score|musical|アニメ|サウンドトラック",
    "Latin": "latin|reggaeton|cumbia|bossa nova|samba|flamenco|regional mexicano|trap latino",
    "Folk": "folk|americana|bluegrass|neofolk",
    "Country": "country|nashville sound|honky tonk",
    "Reggae": "reggae|dub|dancehall|rocksteady|ska|lovers rock",
    "World": "world|worldwide|afrobeat|afrobeats|world fusion",
    "Blues": "blues",
    "Singer/Songwriter": "singer songwriter|singer/songwriter",
    "Spoken Audio": "spoken word|spoken & audio|slam poetry",
    "Instrumental": "instrumental",
    "New Age": "new age|celtic new age",
}

# Keep the last named style in conventional compounds such as jazz rap and folk rock.
FAMILY_SUFFIXES = {
    "rock": "Rock", "punk": "Rock", "metal": "Rock", "metalcore": "Rock", "emo": "Rock",
    "rap": "Hip-Hop / Rap", "hip hop": "Hip-Hop / Rap", "drill": "Hip-Hop / Rap",
    "house": "Dance / Electronic", "techno": "Dance / Electronic", "trance": "Dance / Electronic",
    "dubstep": "Dance / Electronic", "garage": "Dance / Electronic", "electronic": "Dance / Electronic",
    "drum and bass": "Dance / Electronic", "disco": "Dance / Electronic",
    "soul": "R&B / Soul", "r&b": "R&B / Soul", "funk": "R&B / Soul",
    "pop": "Pop", "jazz": "Jazz", "classical": "Classical", "folk": "Folk", "blues": "Blues",
    "country": "Country", "reggae": "Reggae",
}


def norm(text):
    return unicodedata.normalize("NFKC", text or "").strip().casefold()


def artist_label(text):
    return unicodedata.normalize("NFC", text or "").strip()


def genre_key(text):
    return " ".join(norm(text).replace("-", " ").replace("‐", " ").split())


BY_TERM = {genre_key(term): family for family, terms in FAMILY_TERMS.items()
           for term in terms.split("|")}


def family_for(tag):
    tag = genre_key(tag)
    if tag in BY_TERM:
        return BY_TERM[tag]
    for suffix, family in FAMILY_SUFFIXES.items():
        if tag.endswith(" " + suffix):
            return family
    return ""


def unique_winner(votes):
    ranked = votes.most_common(2)
    if ranked and (len(ranked) == 1 or ranked[0][1] > ranked[1][1]):
        return ranked[0][0]
    return ""


def musicbrainz_family(match):
    if not match or not match.get("mbid"):
        return ""
    votes = Counter()
    strongest_unmapped = 0
    for tag, count in match.get("tags", {}).items():
        if type(count) is int and count > 0:
            family = family_for(tag)
            if family:
                votes[family] += count
            else:
                strongest_unmapped = max(strongest_unmapped, count)
    winner = unique_winner(votes)
    return winner if winner and votes[winner] > strongest_unmapped else ""


def container_family(genres):
    tags = {genre_key(g) for g in genres.split(",")} - {"", "music", "n/a"}
    families = {family_for(tag) for tag in tags}
    if "" in families:
        return ""  # An unrecognized tag could identify a conflicting family.
    if len(families) == 1:
        return families.pop()
    regional_pop = families & {"J-Pop", "K-Pop"}
    if len(regional_pop) > 1:
        return ""
    # Only generic labels can be discarded. "Indie Pop, Rock" describes two styles.
    generic = {"pop", "j pop", "japanese pop", "k pop", "korean pop"}
    specific = {family_for(tag) for tag in tags - generic}
    if len(specific) == 1:
        return specific.pop()
    if not specific and len(regional_pop) == 1:
        return regional_pop.pop()
    return ""


def fallback_groups(rows, matches, folder):
    """Return additional artist families; an empty credit never receives a family."""
    artists = {row["artist"] for row in rows if row["artist"] and not row["group"]}
    known = defaultdict(set)
    for row in rows:
        if row["artist"] in artists and row["group"]:
            known[row["artist"]].add(row["group"])
    requested = {artist_label(artist) for artist in artists}
    album_families = defaultdict(set)
    single_credit_families = defaultdict(set)
    for filename in GENRE_INPUT_FILES:
        path = folder / filename
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source, strict=True):
                if None in row or None in row.values():
                    raise ValueError(f"Incomplete or malformed row in {filename}")
                family = container_family(row["Genres"])
                if not family:
                    continue
                # The description explicitly credits the album artist; listed guests
                # on the same album do not inherit that artist's classification.
                if row.get("Container Type") == "ALBUM":
                    artist, separator, title = row["Container Description"].partition(" - ")
                    if separator and title.strip() and artist_label(artist) in requested:
                        album_families[artist_label(artist)].add(family)
                credit = artist_label(row["Artists"])
                if credit in requested and "," not in credit:
                    single_credit_families[credit].add(family)

    choices = {}
    match_rows = (matches or {}).get("artists", {})
    for artist in sorted(artists):
        name = artist_label(artist)
        if len(known[artist]) == 1:
            choices[artist] = next(iter(known[artist]))
            continue
        if known[artist]:
            continue
        families = album_families[name]
        if len(families) == 1:
            choices[artist] = next(iter(families))
            continue
        group = musicbrainz_family(match_rows.get(artist))
        if not group and len(single_credit_families[name]) == 1 and not families:
            group = next(iter(single_credit_families[name]))
        if group:
            choices[artist] = group
    return choices
