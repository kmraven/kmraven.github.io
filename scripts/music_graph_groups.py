"""Infer map regions from nearby labelled artists and explain remaining unknowns."""

from collections import Counter, defaultdict
from hashlib import sha256

from music_genres import family_for
from musicbrainz_match import normalize


def adjacency(edges):
    neighbors = defaultdict(dict)
    for a, b, _, score in edges:
        if a != b and score >= 0.6:
            neighbors[a][b] = neighbors[b][a] = score
    return neighbors


def predict(artist, neighbors, seeds):
    # A path stops at the first labelled artist. Several paths to the same
    # artist still give one vote. No inferred label is ever used as a seed.
    anchors = {}
    for peer, first in neighbors.get(artist, {}).items():
        if peer in seeds:
            anchors[peer] = max(anchors.get(peer, 0), first)
        else:
            for other, second in neighbors[peer].items():
                if other != artist and other in seeds:
                    anchors[other] = max(anchors.get(other, 0), first * second)
    if len(anchors) < 2 or len({seeds[peer] for peer in anchors}) != 1:
        return None
    ordered = sorted(anchors, key=lambda peer: (-anchors[peer], peer))
    return {"group": seeds[ordered[0]], "neighbors": ordered, "method": "tags"}


def validate(neighbors, seeds, reference):
    """Hide a fifth of the seed labels at a time and score eligible predictions."""
    folds = {name: int.from_bytes(sha256(name.encode()).digest()[:4], "big") % 5 for name in seeds}
    scored = []
    for fold in range(5):
        visible = {n: g for n, g in seeds.items() if folds[n] != fold}
        for artist in reference:
            if folds.get(artist) != fold:
                continue
            result = predict(artist, neighbors, visible)
            if result:
                scored.append((artist, result["group"], reference[artist]))
    return scored


def unclassified_reasons(credits, profiles, candidates=None, apple_ids=None):
    candidate_names = None
    if candidates is not None:
        candidate_names = {name for artist in candidates.values() for name in artist["names"]}
        candidate_ids = {identifier for artist in candidates.values() for identifier in artist.get("apple", ())}
    reasons = {}
    for artist in credits:
        profile = profiles.get(artist)
        if not artist:
            reason = "credit-missing"
        elif not profile:
            if candidate_names is None:
                reason = "no-identity"
            else:
                by_id = candidate_ids.intersection((apple_ids or {}).get(artist, ()))
                reason = "identity-unverified" if by_id or normalize(artist) in candidate_names else "no-candidate"
        elif not any(type(v) is int and v > 0 for v in profile["tags"].values()):
            reason = "no-genres"
        else:
            votes = Counter()
            for tag, count in profile["tags"].items():
                family = family_for(tag)
                if family and type(count) is int and count > 0:
                    votes[family] += count
            top = votes.most_common(2)
            reason = "genre-tie" if len(top) == 2 and top[0][1] == top[1][1] else "genre-unmapped"
        reasons[artist] = reason
    return reasons
