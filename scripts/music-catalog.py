"""Cache Apple Music catalog metadata for the audio IDs in a Daily Tracks export."""

import argparse
import csv
import fcntl
import http.client
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.parse import urlencode, urljoin, urlsplit


HOST = "api.music.apple.com"
CATALOG_ID = re.compile(r"[1-9][0-9]*")


class CatalogError(Exception):
    """A diagnostic safe to print without exposing credentials or history."""


class MissingResource(CatalogError):
    pass


def audio_track_ids(source):
    with source.open(encoding="utf-8-sig", newline="") as stream:
        rows = csv.DictReader(stream)
        if not {"Track Identifier", "Media type"}.issubset(rows.fieldnames or []):
            raise CatalogError("Expected a Daily Tracks CSV with Track Identifier and Media type.")
        return {
            row["Track Identifier"].strip() for row in rows
            if row["Media type"] == "AUDIO" and CATALOG_ID.fullmatch((row["Track Identifier"] or "").strip())
        }


def request_page(path, token):
    # Use a fixed HTTPS origin and never forward authorization through redirects.
    for attempt in range(4):
        connection = http.client.HTTPSConnection(HOST, timeout=30)
        delay = 2 ** attempt
        try:
            connection.request("GET", path, headers={"Authorization": f"Bearer {token}"})
            response = connection.getresponse()
            if response.status == 200:
                return json.load(response)
            if response.status == 404:
                raise MissingResource("Catalog resource unavailable.")
            failure = f"Apple Music returned HTTP {response.status}."
            if response.status not in {408, 429, 500, 502, 503, 504}:
                raise CatalogError(failure)
            retry_after = response.getheader("Retry-After", "")
            if retry_after.isdecimal():
                delay = max(delay, int(retry_after))
        except (OSError, http.client.HTTPException):
            failure = "Apple Music connection failed."
        finally:
            connection.close()
        if attempt == 3 or delay > 60:
            raise CatalogError(f"{failure} Rerun to resume.")
        time.sleep(delay)


def resources(path, fetch):
    seen = set()
    first_path = urlsplit(path).path
    while path:
        if path in seen:
            raise CatalogError("Apple Music repeated a page.")
        seen.add(path)
        page = fetch(path)
        if not isinstance(page, dict) or not isinstance(page.get("data"), list):
            raise CatalogError("Invalid Apple Music collection.")
        yield from page["data"]
        next_link = page.get("next")
        if next_link is None:
            return
        if not isinstance(next_link, str) or not next_link:
            raise CatalogError("Invalid Apple Music pagination link.")
        url = urlsplit(urljoin(f"https://{HOST}{path}", next_link))
        if url.scheme != "https" or url.netloc != HOST or url.path != first_path:
            raise CatalogError("Unexpected Apple Music pagination destination.")
        path = f"{url.path}?{url.query}"


def catalog_songs(base, ids, fetch):
    query = urlencode({"ids": ",".join(ids), "include": "artists"})
    try:
        yield from resources(f"{base}/songs?{query}", fetch)
    except MissingResource:
        # A 404 can cover a whole batch. Isolate unavailable IDs without losing neighbors.
        if len(ids) > 1:
            midpoint = len(ids) // 2
            yield from catalog_songs(base, ids[:midpoint], fetch)
            yield from catalog_songs(base, ids[midpoint:], fetch)


def save_cache(path, cache):
    # NamedTemporaryFile creates a mode-0600 file on the destination filesystem.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        try:
            json.dump(cache, stream, ensure_ascii=False, separators=(",", ":"))
            stream.close()
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)


def enrich(ids, storefront, cache, fetch, checkpoint):
    tracks = cache["tracks"]
    similar = cache["similar"]
    base = f"/v1/catalog/{storefront}"
    pending = sorted(ids.difference(tracks))
    for start in range(0, len(pending), 100):
        batch = pending[start:start + 100]
        for song in catalog_songs(base, batch, fetch):
            if song["type"] != "songs" or song["id"] not in batch:
                raise CatalogError("Unexpected song resource.")
            attrs = song["attributes"]
            artists = song["relationships"]["artists"]["data"]
            if not artists:
                continue
            artist = artists[0]
            if artist["type"] != "artists" or not CATALOG_ID.fullmatch(artist["id"]):
                raise CatalogError("Invalid artist relationship.")
            genres = attrs.get("genreNames", [])
            tracks[song["id"]] = {
                "artist": artist.get("attributes", {}).get("name") or attrs["artistName"],
                "artistId": artist["id"],
                "genre": genres[0] if genres else "",
                "title": attrs["name"],
            }
        checkpoint()

    artist_ids = {tracks[track]["artistId"] for track in ids.intersection(tracks)}
    for index, artist_id in enumerate(sorted(artist_ids.difference(similar)), 1):
        try:
            related = []
            for artist in resources(f"{base}/artists/{artist_id}/view/similar-artists", fetch):
                if artist["type"] != "artists" or not CATALOG_ID.fullmatch(artist["id"]):
                    raise CatalogError("Invalid similar artist resource.")
                related.append(artist["id"])
            similar[artist_id] = list(dict.fromkeys(related))
        except MissingResource:
            pass  # Retry unavailable views on the next run.
        if index % 25 == 0:
            checkpoint()
    print(f"Catalog tracks {len(ids.intersection(tracks))}/{len(ids)}; "
          f"artist views {len(artist_ids.intersection(similar))}/{len(artist_ids)}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("daily_tracks", type=Path)
    parser.add_argument("--storefront", default="jp", help="two-letter Apple Music storefront (default jp)")
    parser.add_argument("--cache-dir", type=Path, default=Path("private"), help="private output directory")
    parser.add_argument("--refresh", action="store_true", help="rebuild or resume a fresh catalog snapshot")
    args = parser.parse_args()
    storefront = args.storefront.lower()
    if not re.fullmatch("[a-z]{2}", storefront):
        raise CatalogError("Expected a two-letter storefront.")
    token = os.environ.get("APPLE_MUSIC_DEVELOPER_TOKEN", "").strip()
    if not token or not re.fullmatch(r"[A-Za-z0-9_.-]+", token):
        raise CatalogError("Set APPLE_MUSIC_DEVELOPER_TOKEN to a valid developer token.")
    ids = audio_track_ids(args.daily_tracks)
    args.cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    output = args.cache_dir / f"music-catalog-{storefront}.json"
    current = output.with_suffix(".refresh.json") if args.refresh else output
    with output.with_suffix(".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CatalogError("Another enrichment is writing the same cache.") from None
        cache = {"tracks": {}, "similar": {}}
        if current.exists():
            cache = json.loads(current.read_text(encoding="utf-8"))
            if not all(isinstance(cache.get(key), dict) for key in ("tracks", "similar")):
                raise CatalogError("Invalid catalog cache.")
        try:
            enrich(ids, storefront, cache, lambda path: request_page(path, token),
                   lambda: save_cache(current, cache))
        finally:
            save_cache(current, cache)
        if args.refresh:
            current.replace(output)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("Interrupted. Rerun with the same options to resume.")
    except CatalogError as exc:
        sys.exit(str(exc))
    except (OSError, ValueError, TypeError, AttributeError, KeyError, csv.Error):
        sys.exit("Unable to read or write catalog data. Check the input, cache and Apple Music response.")
