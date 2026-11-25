from pathlib import Path
import csv
import json
import runpy
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile


genres = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/music_genres.py"))


class GenreTest(unittest.TestCase):
    def test_apple_genres_respect_exact_credit_and_verified_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            names = ["LiSA", "LISA", "Verified Alias", "DJ", "Dj"]
            with (folder / "Apple Music - Play History Daily Tracks.csv").open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["Media type", "Track Identifier", "Date Played", "Play Duration Milliseconds",
                                 "Track Description"])
                for index, artist in enumerate(names):
                    writer.writerow(["AUDIO", index + 1, "2025-01-01", 500 - index, f"{artist} - Track"])
            library = "Apple Music Library Tracks.json"
            with ZipFile(folder / (library + ".zip"), "w") as archive:
                archive.writestr(library, json.dumps([{"Artist": "LiSA", "Title": "Track", "Genre": "Anime"}]))
            with (folder / "Apple Music - Container Origin.csv").open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["Container Type", "Container Description", "Artists", "Genres"])
                writer.writerow(["ALBUM", "DJ - Another Record", "DJ", "Jazz"])
            match = {"mbid": "aaaaaaaa-1111-4444-8888-bbbbbbbbbbbb", "tags": {}}
            cache = folder / "matches.json"
            cache.write_text(json.dumps({"artists": {"LiSA": match, "Verified Alias": match}}))
            output = folder / "history.json"
            subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/import-music.py"),
                            str(folder), "--musicbrainz", str(cache), "--output", str(output)],
                           check=True, capture_output=True)
            rows = json.loads(output.read_text())["tracks"]
            self.assertEqual([(r["artist"], r["group"]) for r in rows], [
                ("LiSA", "Anime / Soundtrack"), ("LISA", ""), ("LiSA", "Anime / Soundtrack"),
                ("DJ", "Jazz"), ("Dj", ""),
            ])

    def test_tracks_verified_votes_and_ties(self):
        family = genres["musicbrainz_family"]
        self.assertEqual(family({"mbid": "x", "tags": {"electro house": 3, "house": 2, "pop": 4}}),
                         "Dance / Electronic")
        self.assertEqual(family({"mbid": "x", "tags": {"hip hop": 1, "pop": 1}}), "")
        self.assertEqual(family({"mbid": "x", "tags": {"j-pop": 2, "pop": 0, "rock": -1}}), "J-Pop")
        self.assertEqual(family({"tags": {"hip hop": 20}}), "")
        self.assertEqual(family({"mbid": "x", "tags": {"unmapped genre": 8, "pop": 1}}), "")

    def test_only_generic_pop_can_yield_to_another_style(self):
        family = genres["container_family"]
        self.assertEqual(family("J-Pop, Music, Electronic"), "Dance / Electronic")
        self.assertEqual(family("Pop, J-Pop, Music"), "J-Pop")
        self.assertEqual(family("Dance, Indie Pop, Pop, Music"), "")
        self.assertEqual(family("Electronic, J-Pop, Rock"), "")
        self.assertEqual(family("Electronic, Unmapped Style"), "")
        self.assertEqual(family("K-Pop, J-Pop"), "")

    def test_album_and_single_artist_evidence_preserves_original_classifications(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with (folder / genres["GENRE_INPUT_FILES"][0]).open("w") as source:
                writer = csv.writer(source)
                writer.writerow(["Container Type", "Container Description", "Artists", "Genres"])
                writer.writerow(["ALBUM", "Band & Guest - Joint", "Band, Guest", "Rock, Music"])
                writer.writerow(["PLAYLIST", "Unrelated title", "DJ", "Electronic, J-Pop, Music"])
                writer.writerow(["RADIO", "A playlist", "Other", "Hip Hop/Rap, Music"])
                writer.writerow(["RADIO", "Another", "Other", "Jazz, Music"])
            names = ["Band", "Guest", "Band & Guest", "DJ", "Other", "A", "Resolved", ""]
            rows = [{"artist": a, "group": "Jazz" if a == "Resolved" else ""} for a in names]
            matches = {"artists": {a: {"mbid": "id", "tags": {"j-pop": 3}} for a in ["A", "Resolved"]}}
            result = genres["fallback_groups"](rows, matches, folder)
            self.assertEqual(result, {"Band & Guest": "Rock", "DJ": "Dance / Electronic", "A": "J-Pop"})
            self.assertEqual(rows[-2]["group"], "Jazz")


if __name__ == "__main__":
    unittest.main()
