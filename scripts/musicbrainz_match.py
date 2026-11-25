# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Match whole Apple Music artist credits using a local MusicBrainz artist JSON dump."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import runpy
import sqlite3
import subprocess
from tempfile import NamedTemporaryFile
import unicodedata
from zipfile import ZipFile

from musicbrainz_recordings import normalized_title as normalize, title_variants
from music_artists import INTACT_NAMES, apply_recorded_leads, assign_primary_artists, possible_lead_names


APPLE_ARTIST_URL = re.compile(
    r"https?://(?:geo\.)?(?:music|itunes)\.apple\.com/(?:[a-z]{2}/)?artist/"
    r"(?:[^/?#]+/)?(?:id)?([1-9][0-9]*)/?(?:[?#].*)?$", re.IGNORECASE
)
COLLABORATION = re.compile(r"[,;&、×／/]|\s(?:and|with|feat\.?|featuring|vs\.?|x)\s")
GENERIC_TITLES = {"intro", "introduction", "interlude", "outro", "untitled", "opening", "ending"}
SPECIAL_ARTISTS = {"89ad4ac3-39f7-470e-963a-56509c546377", "125ec42a-7229-4250-afc5-e057484327fe"}


def search_aliases(artist):
    # Expose only the main artist name and explicitly preferred localized stage names.
    # Keep unrelated historical names, legal names, search hints and sort keys out of search.
    primary = artist["name"]
    aliases = {normalize(primary): primary}
    for alias in artist.get("aliases", []):
        locale = re.split("[-_]", alias.get("locale") or "", maxsplit=1)[0].lower()
        if (alias.get("type") == "Artist name" and alias.get("primary") is True
                and not alias.get("ended") and locale in {"ja", "en"}):
            name = alias["name"].strip()
            if name:
                aliases.setdefault(normalize(name), name)
    return [primary, *sorted(name for name in aliases.values() if name != primary)]


def apple_ids(folder):
    library = "Apple Music Library Artists.json"
    path = folder / (library + ".zip")
    identifiers = defaultdict(set)
    if path.exists():
        with ZipFile(path) as archive, archive.open(library) as source:
            for row in json.load(source):
                values = str(row.get("Catalog Identifiers - Artist") or "").split(",")
                label = unicodedata.normalize("NFC", (row.get("Artist Name") or "").strip())
                identifiers[label].update(
                    v.strip() for v in values if re.fullmatch(r"[1-9][0-9]*", v.strip()) and v.strip() != "1"
                )
    return identifiers


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", delete=False) as stream:
        tmp = Path(stream.name)
        try:
            json.dump(data, stream, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            stream.close()
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)


def scan_artists(dump, wanted_names, wanted_ids):
    candidates = {}
    # tar streams the 18 GB JSONL member and decompresses concurrently with Python.
    with subprocess.Popen(["tar", "-xOf", str(dump), "mbdump/artist"], stdout=subprocess.PIPE) as tar:
        try:
            for index, line in enumerate(tar.stdout, 1):
                if index % 500_000 == 0:
                    print(f"Read {index:,} MusicBrainz artists.", flush=True)
                artist = json.loads(line)
                mbid = artist["id"]
                if mbid in SPECIAL_ARTISTS:
                    continue
                names = {normalize(artist["name"])}
                names.update(normalize(a["name"]) for a in artist.get("aliases", []))
                names.intersection_update(wanted_names)
                linked = set()
                if wanted_ids and b"apple.com/" in line:
                    for rel in artist.get("relations", []):
                        url = rel.get("url", {}).get("resource", "")
                        match = APPLE_ARTIST_URL.fullmatch(url)
                        if match and match[1] in wanted_ids:
                            linked.add(match[1])
                if names or linked:
                    tags = {g["name"]: g["count"] for g in artist["genres"] if g["count"] > 0}
                    candidates[mbid] = {"names": sorted(names), "apple": sorted(linked),
                                        "tags": tags, "aliases": search_aliases(artist)}
        finally:
            tar.stdout.close()
        if tar.wait():
            raise ValueError("Unable to read the complete mbdump/artist archive member.")
    return candidates


def candidates_for(dump, cache_path, wanted_names, wanted_ids):
    stat = dump.stat()
    selection = json.dumps([sorted(wanted_names), sorted(wanted_ids)], ensure_ascii=False)
    fingerprint = [2, str(dump.resolve()), stat.st_size, stat.st_mtime_ns,
                   hashlib.sha256(selection.encode()).hexdigest()]
    if cache_path.exists():
        saved = json.loads(cache_path.read_text())
        if saved.get("fingerprint") == fingerprint:
            return saved["artists"]
    candidates = scan_artists(dump, wanted_names, wanted_ids)
    end = dump.stat()
    if (stat.st_size, stat.st_mtime_ns) != (end.st_size, end.st_mtime_ns):
        raise ValueError("The artist dump changed during the scan. Rerun after download.")
    write_json(cache_path, {"fingerprint": fingerprint, "artists": candidates})
    return candidates


def credit_tracks(history):
    credits = defaultdict(lambda: defaultdict(set))
    for track in history["tracks"]:
        if track["artist"]:
            # Legacy histories without identifiers can only distinguish tracks by title.
            key = ("id", track["id"]) if track.get("id") else ("title", normalize(track["title"]))
            titles = title_variants(track)
            evidence = credits[track["artist"]][key]
            evidence.update(("", title) for title in titles)
            full_credit = normalize(track.get("credit"))
            if full_credit and full_credit != normalize(track["artist"]):
                evidence.update((full_credit, title) for title in titles)
    return credits


def recording_support(tracks, recordings):
    """Return 0, 1 or at least 2 independent matches for this candidate artist."""
    previous = []
    for variants in tracks.values():
        hits = variants & recordings.keys()
        if hits:
            ids = set().union(*(recordings[hit] for hit in hits))
            if any(variants.isdisjoint(titles) and ids.isdisjoint(other_ids) for titles, other_ids in previous):
                return 2
            previous.append((variants, ids))
    return int(bool(previous))


def match_credits(credits, identifiers, candidates, db):
    by_name = defaultdict(set)
    by_id = defaultdict(set)
    for mbid, artist in candidates.items():
        for name in artist["names"]:
            by_name[name].add(mbid)
        for apple_id in artist["apple"]:
            by_id[apple_id].add(mbid)
    owners = defaultdict(set)
    for name, ids in identifiers.items():
        for apple_id in ids:
            owners[apple_id].add(name)

    library_matches = {}
    for label, ids in identifiers.items():
        linked = set().union(*(by_id[i] for i in ids))
        if not linked:
            continue
        library_matches[label] = None  # Conflicting source IDs cannot confirm this label.
        if len(linked) != 1 or any(not by_id[i] for i in ids):
            continue
        identity = next(iter(linked))
        name = normalize(label)
        if name not in candidates[identity]["names"] and (
            COLLABORATION.search(name) or any(len(owners[i]) > 1 for i in ids)
        ):
            continue
        library_matches[label] = identity
        # Another spelling of this label can nominate the artist for a recording
        # check. Only the exact library label inherits the catalog ID directly.
        by_name[name].add(identity)

    evidence = {}
    # Existing local indexes may contain titles alone. Those still supply exact title evidence.
    columns = {r[1] for r in db.execute("PRAGMA table_info(credit_recordings)")} if db is not None else set()
    recording_col = "recording_mbid" if "recording_mbid" in columns else "NULL"
    credit_col = "credit" if "credit" in columns else "''"
    select_evidence = f"SELECT title, {recording_col}, {credit_col} FROM credit_recordings WHERE mbid = ?"
    matches = {}
    for credit, tracks in credits.items():
        name = normalize(credit)
        label = unicodedata.normalize("NFC", credit.strip())
        mbid = None
        if label in library_matches:
            mbid, method = library_matches[label], "apple-id"
        elif db is not None and len(identifiers.get(label, ())) <= 1 and by_name[name]:
            supported = {}
            for identity in by_name[name]:
                if identity not in evidence:
                    recordings = defaultdict(set)
                    for title, recording_id, full_credit in db.execute(select_evidence, (identity,)):
                        title = normalize(title)
                        if len(title) > 1 and not title.isdecimal() and title not in GENERIC_TITLES:
                            ids = recordings[full_credit, title]
                            if recording_id:
                                ids.add(recording_id)
                    evidence[identity] = recordings
                support = recording_support(tracks, evidence[identity])
                if support:
                    supported[identity] = support
            if len(supported) == 1:
                identity, count = next(iter(supported.items()))
                if len(by_name[name]) == 1 or count >= 2:
                    mbid, method = identity, "name+recording"
        if mbid:
            matches[credit] = {"mbid": mbid, "tags": candidates[mbid]["tags"], "method": method,
                               "aliases": candidates[mbid]["aliases"]}
    return matches


def lead_candidates(credits, catalog_tracks):
    names = {normalize(name) for name in credits}
    names.update(normalize(p) for name in credits for p in possible_lead_names(name))
    names.update(normalize(row["artist"]) for row in catalog_tracks.values() if row.get("artist"))
    return names


def joint_recording_leads(tracks, matches, candidates, db):
    """Check unsplit credits against the actual credited participants on the recording."""
    if db is None or not any(col[1] == "credit" for col in db.execute("PRAGMA table_info(credit_recordings)")):
        return {}
    by_name = defaultdict(list)
    for mbid, candidate in candidates.items():
        for name in candidate["names"]:
            by_name[name].append(mbid)
    found = {}
    intact = {normalize(name) for name in INTACT_NAMES}
    for track in tracks:
        credit = track["artist"]
        if track.get("credit") or credit in matches or normalize(credit) in intact or not track.get("id"):
            continue
        titles = title_variants(track) - GENERIC_TITLES
        for lead in reversed(possible_lead_names(credit)):
            supported = []
            for mbid in by_name[normalize(lead)]:
                rows = db.execute("SELECT title FROM credit_recordings WHERE mbid = ? AND credit = ?",
                                  (mbid, normalize(credit)))
                if any(normalize(row[0]) in titles for row in rows):
                    supported.append(mbid)
            if supported:
                if len(supported) == 1:
                    found[track["id"]] = {"credit": credit, "lead": lead}
                break
    return found


def match(archive: Path, folder: Path, history: dict, recordings: Path | None, output: Path,
          *, lead_catalog=None) -> dict:
    credits = credit_tracks(history)
    wanted = (lead_candidates(credits, lead_catalog) if lead_catalog is not None
              else {normalize(credit) for credit in credits})
    identifiers = apple_ids(folder)
    wanted_ids = {i for label, ids in identifiers.items() if normalize(label) in wanted for i in ids}
    candidates = candidates_for(archive, output.with_name("candidates.json"), wanted, wanted_ids)
    db = sqlite3.connect(recordings.resolve().as_uri() + "?mode=ro", uri=True) if recordings else None
    protected = []
    member_names = []
    recorded = {}
    try:
        matches = match_credits(credits, identifiers, candidates, db)
        if lead_catalog is not None:
            protected = sorted({name for candidate in candidates.values() for name in candidate["aliases"]
                                if normalize(name) in wanted})
            prefixes = {normalize(p) for credit in credits for p in possible_lead_names(credit)}
            member_names = sorted(prefixes.intersection(name for c in candidates.values() for name in c["names"]))
            assign_primary_artists(history["tracks"], matches, lead_catalog, protected, member_names)
            recorded = joint_recording_leads(history["tracks"], matches, candidates, db)
            apply_recorded_leads(history["tracks"], recorded)
            leads = credit_tracks(history)
            unconfirmed = {name: tracks for name, tracks in leads.items() if name not in matches}
            matches.update(match_credits(unconfirmed, identifiers, candidates, db))
    finally:
        if db:
            db.close()
    result = {"artists": matches}
    if protected:
        result["knownArtistNames"] = protected
    if member_names:
        result["possibleMemberNames"] = member_names
    if recorded:
        result["recordingLeads"] = recorded
    write_json(output, result)
    print(f"Matched {len(matches):,} of {len(credits):,} credits. "
          f"{sum(bool(m['tags']) for m in matches.values()):,} have controlled genres.")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="Apple Music Activity directory")
    parser.add_argument("--history", type=Path, help="override source credits with a listening-history JSON file")
    parser.add_argument("--dump", type=Path, default=Path("private/musicbrainz/artist.tar.xz"))
    parser.add_argument("--recordings", type=Path, help="SQLite database of canonical MusicBrainz recordings")
    parser.add_argument("--output", type=Path, default=Path("private/musicbrainz/matches.json"))
    args = parser.parse_args()
    recordings = Path("private/musicbrainz/recordings.sqlite")
    db = args.recordings or (recordings if recordings.exists() else None)
    if args.history:
        history = json.loads(args.history.read_text(encoding="utf-8"))
    else:
        build = runpy.run_path(str(Path(__file__).with_name("import-music.py")))["build"]
        history = build(args.folder, {})
    for track in history["tracks"]:
        if track.get("credit"):
            track["artist"] = track.pop("credit")
    match(args.dump, args.folder, history, db, args.output, lead_catalog={})


if __name__ == "__main__":
    main()
