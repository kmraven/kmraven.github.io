"""Incrementally cache JP Apple track genres and Wikidata artist genres by public IDs."""

import fcntl
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID


HEADERS = {"User-Agent": "myportal/1.0 (music genre metadata; github.com/kmraven/myportal)"}
APPLE_KEYS = ("appleTracks", "appleNoSpecificGenre")
WIKI_KEYS = ("wikidataByMusicBrainzArtistId", "wikidataNoEntity")
INVALID_GENRES = {"", "music", "other", "unclassifiable"}
SOURCE_ERRORS = (OSError, HTTPException, ValueError, KeyError)


class GenreRefreshError(OSError):
    """A retryable refresh failure with a UNIX timestamp for the next import."""

    def __init__(self, message, retry_at=None):
        super().__init__(message)
        self.retry_at = retry_at if retry_at is not None else time.time() + 60


def _load(path):
    seed = path.with_name("genre-source-audit.json")
    for source in (path, seed):
        if source.exists():
            cache = json.loads(source.read_text(encoding="utf-8"))
            if cache["storefront"] != "JP":
                raise ValueError(f"Expected JP storefront in {source}")
            return cache
    return {"appleSource": "https://performance-partners.apple.com/search-api",
            "storefront": "JP", "appleTracks": {}, "appleNoSpecificGenre": [],
            "wikidataSource": "https://query.wikidata.org/",
            "wikidataByMusicBrainzArtistId": {}, "wikidataNoEntity": []}


def _save(path, cache):
    with NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as out:
        temp = Path(out.name)
        try:
            json.dump(cache, out, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            out.flush()
            os.fsync(out.fileno())
            out.close()
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


def _apple(ids):
    url = "https://itunes.apple.com/lookup?" + urlencode(
        {"id": ",".join(ids), "country": "JP", "lang": "en_us", "limit": 200})
    with urlopen(Request(url, headers=HEADERS), timeout=35) as response:
        data = json.load(response)
    if (not isinstance(data, dict) or not isinstance(data.get("results"), list)
            or data.get("resultCount") != len(data["results"])):
        raise ValueError("Incomplete iTunes response")
    found = {}
    for row in data["results"]:
        if not isinstance(row, dict) or "wrapperType" not in row:
            raise ValueError("Malformed iTunes lookup result")
        if row["wrapperType"] != "track" or row.get("kind") != "song":
            continue
        key = str(row["trackId"])
        genre = row.get("primaryGenreName") or ""
        if key in ids and genre.strip().casefold() not in INVALID_GENRES:
            found[key] = {k: row.get(k) for k in ("artistId", "artistName", "primaryGenreName", "trackName")}
    return found


def _entity(uri):
    match = re.fullmatch(r"https?://www\.wikidata\.org/entity/(Q[1-9][0-9]*)", uri)
    if not match:
        raise ValueError("Unexpected Wikidata entity URI")
    return match[1]


def _wikidata(ids):
    literals = " ".join(json.dumps(i) for i in ids)
    query = ("SELECT DISTINCT ?mb ?artist ?genre ?label WHERE { VALUES ?mb { " + literals
             + ' } ?artist wdt:P434 ?mb . OPTIONAL { ?artist wdt:P136 ?genre . '
             + 'OPTIONAL { ?genre rdfs:label ?label . FILTER(LANG(?label)="en") } } }')
    request = Request("https://query.wikidata.org/sparql",
                      data=urlencode({"query": query, "format": "json"}).encode(),
                      headers={**HEADERS, "Accept": "application/sparql-results+json"})
    with urlopen(request, timeout=75) as response:
        rows = json.load(response)["results"]["bindings"]
    if not isinstance(rows, list):
        raise ValueError("Incomplete Wikidata response")
    found = {}
    for row in rows:
        identifier = row["mb"]["value"]
        if identifier not in ids:
            raise ValueError("Unexpected artist in Wikidata response")
        artist = _entity(row["artist"]["value"])
        genres = found.setdefault(identifier, {}).setdefault(artist, {})
        if "genre" in row:
            genre = _entity(row["genre"]["value"])
            genres[genre] = row.get("label", {}).get("value") or genre
    return found


def _retry_after(header):
    if not header:
        return 0
    if header.isdecimal():
        return int(header)
    try:
        return max(0, (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return 0


def _update(path, cache, ids, keys, fetch, size, interval, refresh):
    found_key, miss_key = keys
    missed = set(cache[miss_key])
    missing = sorted(ids if refresh else ids.difference(cache[found_key], missed))
    # Persist each provider's next request time so quick restarts respect its limit.
    rate = path.with_name(path.name + "." + found_key + ".rate")
    next_call = rate.stat().st_mtime if rate.exists() else 0
    for start in range(0, len(missing), size):
        batch = missing[start:start + size]
        for attempt in range(3):
            wait = next_call - time.time()
            if wait > 300:
                allowed = datetime.fromtimestamp(next_call, timezone.utc).isoformat(timespec="seconds")
                raise GenreRefreshError(f"Provider requested a retry after {allowed}", next_call)
            time.sleep(max(0, wait))
            next_call = time.time() + interval
            rate.touch()
            os.utime(rate, (next_call, next_call))
            try:
                found = fetch(batch)
                break
            except SOURCE_ERRORS as exc:
                if isinstance(exc, HTTPError) and exc.code < 500 and exc.code not in (408, 429):
                    raise
                delay = _retry_after(exc.headers.get("Retry-After")) if isinstance(exc, HTTPError) else 0
                next_call = max(next_call, time.time() + max(delay, 2 ** (attempt + 1)))
                os.utime(rate, (next_call, next_call))
                if attempt == 2 or delay > 300:
                    raise GenreRefreshError(str(exc), max(next_call, time.time() + 60)) from exc
                print(f"{found_key} retrying after {exc}", file=sys.stderr, flush=True)
        for identifier in set(batch) - found.keys():
            cache[found_key].pop(identifier, None)
            missed.add(identifier)
        cache[found_key].update(found)
        missed.difference_update(found)
        cache[miss_key] = sorted(missed)
        _save(path, cache)
        print(f"{found_key} checked {start + len(batch)}/{len(missing)}", file=sys.stderr, flush=True)


def refresh_sources(path, track_ids, mbids, *, refresh=False):
    """Return the full cache. Failures leave completed batches available for the next run."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    songs = {str(i) for i in track_ids if str(i) != "1" and re.fullmatch(r"[1-9][0-9]*", str(i))}
    artists = {str(UUID(i)) for i in mbids if i}
    errors = []
    # The separate lock survives each atomic cache replacement.
    with path.with_name(path.name + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cache = _load(path)
        if not path.exists():
            _save(path, cache)
        for args in ((artists, WIKI_KEYS, _wikidata, 1500, 61),
                     (songs, APPLE_KEYS, _apple, 180, 3.2)):
            try:
                _update(path, cache, *args, refresh)
            except SOURCE_ERRORS as exc:
                errors.append((args[1][0], exc))
        if errors:
            retry_at = max(getattr(exc, "retry_at", time.time() + 60) for _, exc in errors)
            message = ", ".join(f"{provider}: {exc}" for provider, exc in errors)
            raise GenreRefreshError("Genre refresh incomplete: " + message, retry_at)
        return cache
