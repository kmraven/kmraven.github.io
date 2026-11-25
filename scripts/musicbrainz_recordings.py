"""Cache recording-title evidence from the public canonical MusicBrainz snapshot."""

import codecs
import csv
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import tarfile
import tempfile
import unicodedata


def normalized_title(title):
    return " ".join(unicodedata.normalize("NFKC", title or "").casefold().split())


def title_variants(track):
    return {normalized_title(title) for title in (track["title"], *track.get("titleAliases", ())) if title}


def recording_index(archive, history, database):
    titles = {title for track in history["tracks"] for title in title_variants(track)}
    credits = {normalized_title(track.get("credit") or track.get("artist")) for track in history["tracks"]} - {""}
    stat = archive.stat()
    stamp = f"3:{stat.st_size}:{stat.st_mtime_ns}"
    inputs = sha256(json.dumps([sorted(titles), sorted(credits)], ensure_ascii=False).encode()).hexdigest()
    if database.exists():
        with sqlite3.connect(database) as db:
            if db.execute("SELECT snapshot, titles FROM inputs").fetchone() == (stamp, inputs):
                return database

    print("Indexing MusicBrainz recordings for the observed titles…", flush=True)
    with tempfile.TemporaryDirectory(dir=database.parent) as tmp:
        path = Path(tmp, "index.sqlite")
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE inputs (snapshot TEXT, titles TEXT)")
            db.execute("INSERT INTO inputs VALUES (?, ?)", (stamp, inputs))
            db.execute("CREATE TABLE credit_recordings (mbid TEXT, title TEXT, recording_mbid TEXT, credit TEXT, "
                       "PRIMARY KEY (mbid, credit, title, recording_mbid)) WITHOUT ROWID")
            with subprocess.Popen(["zstd", "-dc", str(archive)], stdout=subprocess.PIPE) as proc:
                try:
                    found = False
                    with tarfile.open(fileobj=proc.stdout, mode="r|", bufsize=1024*1024) as tar:
                        for member in tar:
                            if member.name.split("/")[-1] != "canonical_musicbrainz_data.csv":
                                continue
                            with tar.extractfile(member) as stream:
                                rows = csv.reader(codecs.iterdecode(stream, "utf-8"), strict=True)
                                fields = next(rows)
                                artist, title = fields.index("artist_mbids"), fields.index("recording_name")
                                recording = fields.index("recording_mbid") if "recording_mbid" in fields else None
                                credit = fields.index("artist_credit_name") if "artist_credit_name" in fields else None
                                def relevant():
                                    for row in rows:
                                        if normalized_title(row[title]) not in titles:
                                            continue
                                        recording_id = row[recording] if recording is not None else ""
                                        if len(row[artist]) == 36:
                                            yield row[artist], row[title], recording_id, ""
                                        elif credit is not None and recording_id:
                                            full_name = normalized_title(row[credit])
                                            participants = row[artist].split(",")
                                            if (full_name in credits and len(participants) > 1
                                                    and all(len(mbid) == 36 for mbid in participants)):
                                                for mbid in participants:
                                                    yield mbid, row[title], recording_id, full_name
                                db.executemany("INSERT OR IGNORE INTO credit_recordings VALUES (?, ?, ?, ?)", relevant())
                            found = True
                            break
                    if not found:
                        raise ValueError("Canonical snapshot contains no recording metadata")
                    # Validate the compressed stream, including the trailing redirect tables.
                    while proc.stdout.read(1024 * 1024):
                        pass
                    if proc.wait():
                        raise ValueError("Incomplete or corrupt canonical MusicBrainz snapshot")
                finally:
                    proc.stdout.close()
                    if proc.poll() is None:
                        proc.terminate()
        current = archive.stat()
        if (current.st_size, current.st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
            raise ValueError("Canonical snapshot changed during indexing")
        path.replace(database)
    return database
