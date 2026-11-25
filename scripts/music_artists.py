"""Unify evidenced artist identities, retaining their credited names for search."""

from collections import Counter, defaultdict
import re
import unicodedata


# These established names can occur even on an import without a catalog or
# MusicBrainz snapshot. All other identified full artist names also take priority.
INTACT_NAMES = {"Earth, Wind & Fire", "Fear, and Loathing in Las Vegas", "CHiCO with HoneyWorks"}
LEAD_SEPARATOR = re.compile(
    r"\s*[,，](?!\s*(?:Jr\.?|Sr\.?|II|III|IV)(?:$|\s|,))\s*|\s*[、×;；]\s*|"
    r"\s*[（(]?\b(?:feat(?:uring)?|ft)(?:\.\s*|\s+)|"
    r"\s+(?:&|＆|and|with|vs\.?|x|loves|/|／)\s+(?![&＆、,×])|[&＆/／]|"
    r"(?P<open>[（(【\[])|(?P<close>[）)】\]])",
    re.IGNORECASE,
)


def _name_key(name):
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def _separators(credit):
    depth = 0
    for token in LEAD_SEPARATOR.finditer(credit):
        if token.lastgroup == "open":
            depth += 1
        elif token.lastgroup == "close":
            depth = max(0, depth - 1)
        elif not depth and credit[:token.start()].strip() and credit[token.end():].strip():
            yield token


def possible_lead_names(credit):
    """Prefixes to check against an artist database, including names with punctuation."""
    return [credit[:s.start()].strip() for s in _separators(credit)]


def assign_primary_artists(rows, matches, catalog_tracks=None, artist_names=(), member_names=()):
    """Assign each joint credit once, preserving its full source spelling on the row."""
    catalog_tracks = catalog_tracks or {}
    official = {_name_key(n) for n in INTACT_NAMES}
    official.update(_name_key(n) for n in artist_names)
    for label, match in matches.items():
        aliases = {_name_key(a) for a in match.get("aliases", ())}
        official.update(aliases)
        # Some database aliases name a guest alongside the artist (e.g.
        # "Dillon Francis & DJ Snake" is registered to Dillon Francis).
        if not any(_name_key(p) in aliases for p in possible_lead_names(label)):
            official.add(_name_key(label))
    observed = {_name_key(r["artist"]) for r in rows if r["artist"]}
    known = official | observed
    possible_members = {_name_key(n) for n in member_names}
    for row in rows:
        credit = row["artist"]
        if _name_key(credit) in official:
            continue
        separators = list(_separators(credit))
        if not separators:
            continue
        prefixes = [credit[:s.start()].strip() for s in separators]
        # Bare punctuation inside a name (Au/Ra, SOIL&“PIMP”SESSIONS) is
        # weaker evidence than a spaced or explicit delimiter in the same credit.
        first = next((p for p, s in zip(prefixes, separators)
                      if s.group() not in {"&", "＆", "/", "／"}), prefixes[0])
        # A registered group can itself be the first participant. Preserve the
        # longest official prefix before considering individual words or names.
        lead = next((p for p in reversed(prefixes) if _name_key(p) in official), "")
        catalog = catalog_tracks.get(row["id"], {})
        artist_id = str(catalog.get("artistId") or "")
        apple = (catalog.get("artist") or "").strip() if artist_id.isdecimal() and int(artist_id) > 1 else ""
        guests = {_name_key(credit[s.end():end]) for s, end in
                  zip(separators, [s.start() for s in separators[1:]] + [len(credit)])}
        if not lead and apple and _name_key(apple) != _name_key(credit):
            apple_prefix = next((p for p in prefixes if _name_key(p) == _name_key(apple)), "")
            if apple_prefix:
                lead = apple_prefix
            elif _name_key(apple) in guests:
                # The storefront can list another participant first. The source
                # credit determines ordering when both spellings are available.
                lead = first
            elif not possible_lead_names(apple):
                lead = apple
        if not lead:
            lead = next((p for p in prefixes if _name_key(p) in observed), "")
        spaced_list = any(s.group().strip() in {"&", "＆", ",", "，"} and s.group() != s.group().strip()
                          for s in separators)
        if not lead and spaced_list and _name_key(first) in possible_members:
            lead = first
        if not lead and (guests & known or any(re.search(r"[、×]|feat|\bft", s.group(), re.IGNORECASE)
                                                for s in separators)):
            lead = first
        if lead:
            row.setdefault("credit", credit)
            row["artist"] = lead


def apply_recorded_leads(rows, recorded):
    for row in rows:
        proof = recorded.get(row.get("id"))
        if proof and row["artist"] == proof["credit"]:
            row["credit"] = row["artist"]
            row["artist"] = proof["lead"]


def canonicalize(rows, musicbrainz):
    matches = musicbrainz["artists"]
    durations = Counter()
    for row in rows:
        durations[row["artist"]] += sum(row["years"].values())
    names_by_id = defaultdict(list)
    for name in sorted(durations):
        if name and matches.get(name, {}).get("mbid"):
            names_by_id[matches[name]["mbid"]].append(name)

    canonical = {}
    aliases = {}
    profiles = {}
    for mbid, spellings in names_by_id.items():
        display = min(spellings, key=lambda name: (-durations[name], name))
        search_names = set(spellings)
        tags = Counter()
        for name in spellings:
            canonical[name] = display
            search_names.update(matches[name].get("aliases", ()))
            tags |= Counter(matches[name].get("tags", {}))
        profiles[display] = {"mbid": mbid, "tags": dict(tags)}
        search_names.discard(display)
        if search_names:
            aliases[display] = sorted(search_names)

    # An artist occupies one map region. Across aliases, use the existing Apple
    # classification which accounts for the most listening with a known group.
    group_times = defaultdict(Counter)
    for row in rows:
        row["artist"] = canonical.get(row["artist"], row["artist"])
        if row["artist"] and row["group"]:
            group_times[row["artist"]][row["group"]] += sum(row["years"].values())
    families = {}
    for artist, votes in group_times.items():
        top = votes.most_common(2)
        families[artist] = top[0][0] if len(top) == 1 or top[0][1] > top[1][1] else ""
    for row in rows:
        if row["artist"]:
            row["group"] = families.get(row["artist"], "")
    return {"artists": profiles}, aliases
