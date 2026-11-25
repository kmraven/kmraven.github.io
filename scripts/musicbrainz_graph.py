"""Build explained, undirected similarities from matched MusicBrainz genre votes."""

from collections import Counter, defaultdict
from math import log, sqrt
import unicodedata
from uuid import UUID


# These family names alone describe too wide a range of music to justify an edge.
BROAD_GENRES = {
    "alternative", "alternative rock", "blues", "classical", "country", "dance", "electronic",
    "electronica", "experimental", "folk", "funk", "hip hop", "hip-hop", "house", "indie",
    "indie rock", "instrumental", "j-pop", "jazz", "k-pop", "latin", "metal", "pop", "pop rock",
    "punk", "r&b", "rap", "reggae", "rock", "singer-songwriter", "soul", "soundtrack", "world",
}


def musicbrainz_graph(cache, credit_ms):
    matches = cache["artists"]
    by_id = defaultdict(list)
    votes = defaultdict(Counter)
    for credit in sorted(credit_ms):
        if not credit:
            continue
        match = matches.get(credit)
        if not match or not match.get("mbid"):
            continue
        identifier = str(UUID(match["mbid"]))
        by_id[identifier].append(credit)
        for tag, count in match.get("tags", {}).items():
            tag = unicodedata.normalize("NFKC", tag).strip().casefold()
            if tag and type(count) is int and count > 0:
                # An alias can carry another copy of the same MusicBrainz artist profile.
                votes[identifier][tag] = max(votes[identifier][tag], count)

    df = Counter(tag for tags in votes.values() for tag in tags)
    weights = {}
    postings = defaultdict(list)
    for identifier, tags in votes.items():
        weighted = {tag: (1 + log(count)) * (1 + log((1 + len(votes)) / (1 + df[tag])))
                    for tag, count in sorted(tags.items())}
        norm = sqrt(sum(value ** 2 for value in weighted.values()))
        weights[identifier] = {tag: value / norm for tag, value in weighted.items()}
        for tag in weighted:
            postings[tag].append(identifier)

    neighbors = {}
    for identifier, vector in weights.items():
        scores = Counter()
        common = Counter()
        rare_matches = set()
        for tag, weight in vector.items():
            rare = tag not in BROAD_GENRES and df[tag] <= max(2, 0.02 * len(weights))
            for candidate in postings[tag]:
                if candidate != identifier:
                    scores[candidate] += weight * weights[candidate][tag]
                    common[candidate] += 1
                    if rare:
                        rare_matches.add(candidate)
        ranked = sorted((round(score, 12), common[candidate], candidate)
                        for candidate, score in scores.items()
                        if round(score, 12) >= 0.35 and (common[candidate] >= 2 or candidate in rare_matches))
        ranked.reverse()
        top = ranked[:3]
        # If the cutoff splits an indistinguishable group, omit the whole tied group.
        if len(ranked) > 3 and ranked[3][:2] == top[-1][:2]:
            top = [entry for entry in top if entry[:2] != ranked[3][:2]]
        neighbors[identifier] = {candidate: score for score, _, candidate in top}

    representative = {identifier: min(names, key=lambda name: (-credit_ms[name], name))
                      for identifier, names in by_id.items()}
    edges = []
    linked_ids = set()
    for a, candidates in neighbors.items():
        for b, score in candidates.items():
            if a >= b or a not in neighbors[b]:
                continue
            shared = weights[a].keys() & weights[b].keys()
            tags = sorted(shared, key=lambda tag: (-weights[a][tag] * weights[b][tag], tag))
            left, right = sorted((representative[a], representative[b]))
            edges.append([left, right, tags, round(score, 6)])
            linked_ids.update((a, b))

    matched = {name for names in by_id.values() for name in names}
    tagged = {name for identifier in votes for name in by_id[identifier]}
    linked = {representative[identifier] for identifier in linked_ids}
    stats = {"totalCredits": len(credit_ms.keys() - {""}), "totalMs": sum(credit_ms.values()),
             "namedMs": sum(ms for name, ms in credit_ms.items() if name),
             "matchedMbids": len(by_id), "taggedMbids": len(votes), "linkedMbids": len(linked_ids),
             "edgeCount": len(edges)}
    for prefix, credits in (("matched", matched), ("tagged", tagged), ("linked", linked)):
        stats[f"{prefix}Credits"] = len(credits)
        stats[f"{prefix}Ms"] = sum(credit_ms[name] for name in credits)
    return sorted(edges), stats
