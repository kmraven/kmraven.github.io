# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Refresh the two official MusicBrainz snapshots for offline artist matching."""

import argparse
from hashlib import file_digest
from pathlib import Path
import re
import subprocess


BASE = "https://data.metabrainz.org/pub/musicbrainz"
CANONICAL = r"musicbrainz-canonical-dump-\d{8}-\d{6}"


def read_url(url):
    return subprocess.check_output(["curl", "-fsSL", "--retry", "3", url], text=True)


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def fetch(directory, filename, url, checksum):
    destination = directory / filename
    if destination.is_file() and digest(destination) == checksum:
        print(f"{filename} is current.")
        return
    # Keep a dated partial file so another edition can never be appended to it.
    partial = directory / f"{filename}.{checksum[:12]}.part"
    if not partial.is_file() or digest(partial) != checksum:
        subprocess.run(["curl", "--http1.1", "-fL", "--retry", "3", "--retry-all-errors",
                        "-C", "-", "-o", str(partial), url], check=True)
    if digest(partial) != checksum:
        partial.unlink()
        raise ValueError(f"SHA-256 mismatch for {filename}. Run again to download a fresh copy.")
    partial.replace(destination)
    print(f"Verified {filename} from {url}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=Path("private/musicbrainz"))
    directory = parser.parse_args().directory
    directory.mkdir(parents=True, exist_ok=True)
    artists = f"{BASE}/data/json-dumps"
    date = read_url(f"{artists}/LATEST").strip()
    if not re.fullmatch(r"\d{8}-\d{6}", date):
        raise ValueError("Unexpected MusicBrainz artist snapshot name")
    checksums = read_url(f"{artists}/{date}/SHA256SUMS")
    entry = re.search(r"^([0-9a-f]{64})\s+\*?artist\.tar\.xz\s*$", checksums, re.M)
    if not entry:
        raise ValueError("No checksum for the artist snapshot")
    canonical = f"{BASE}/canonical_data"
    latest = max(re.findall(r'href="(' + CANONICAL + r')/"', read_url(canonical + "/")))
    url = f"{canonical}/{latest}/{latest}.tar.zst"
    canonical_hash = read_url(url + ".sha256").split()[0]
    if not re.fullmatch(r"[a-f0-9]{64}", canonical_hash):
        raise ValueError("Unexpected MusicBrainz canonical checksum")
    fetch(directory, "artist.tar.xz", f"{artists}/{date}/artist.tar.xz", entry[1])
    fetch(directory, "canonical.tar.zst", url, canonical_hash)


if __name__ == "__main__":
    main()
