import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import UUID


class StyleImportTest(unittest.TestCase):
    def test_style_graph_and_track_genres_can_disagree(self):
        importer = Path(__file__).resolve().parents[1] / "scripts/import-music.py"
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            acts = ["Band A", "Band B", "Solo", "Solo", "Solo"]
            with (base / "Apple Music - Play History Daily Tracks.csv").open("w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Media type", "Track Identifier", "Date Played", "Play Duration Milliseconds",
                                 "Track Description"])
                for i, artist in enumerate(acts, 10):
                    writer.writerow(["AUDIO", i, "2025-01-01", i * 100, f"{artist} - Track {i}"])
            left, right = (str(UUID(int=i)) for i in (1, 2))
            (base / "matches.json").write_text(json.dumps({"artists": {
                "Band A": {"mbid": left, "tags": {"post-rock": 1}},
                "Band B": {"mbid": right, "tags": {}},
            }}))
            songs = {
                str(i): {"primaryGenreName": genre} for i, genre in enumerate(
                    ["Anime", "J-Pop", "R&B/Soul", "R&B/Soul", "Hip-Hop/Rap"], 10)
            }
            (base / "sources.json").write_text(json.dumps({
                "storefront": "JP", "appleTracks": songs, "wikidataByMusicBrainzArtistId": {
                    right: {"Q123": {"Q456": "post-rock"}}
                },
            }))
            subprocess.run([sys.executable, str(importer), str(base), "--musicbrainz", str(base / "matches.json"),
                            "--genre-sources", str(base / "sources.json"), "--output", str(base / "history.json")],
                           check=True, capture_output=True)
            result = json.loads((base / "history.json").read_text())
            self.assertEqual(result["relation"], "style")
            self.assertEqual(len(result["tracks"]), 5)
            self.assertEqual([r["appleGenre"] for r in result["tracks"]], [s["primaryGenreName"] for s in songs.values()])
            self.assertEqual([r["group"] for r in result["tracks"]], ["Rock", "Rock", *(["R&B / Soul"] * 3)])
            self.assertEqual([r["years"]["2025"] for r in result["tracks"]], [i * 100 for i in range(10, 15)])
            self.assertEqual(result["artistStyles"]["Solo"]["method"], "apple-tracks")
            self.assertEqual(result["artistStyles"]["Solo"]["appleGenres"], {"R&B/Soul": 2, "Hip-Hop/Rap": 1})
            self.assertEqual(len(result["edges"]), 1)
            self.assertEqual(result["edges"][0][:2], ["Band A", "Band B"])
