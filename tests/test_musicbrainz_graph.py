import csv
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from uuid import UUID


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
graph = runpy.run_path(str(SCRIPTS / "musicbrainz_graph.py"))["musicbrainz_graph"]


def match(identifier, tags):
    return {"mbid": str(UUID(int=identifier)), "tags": tags, "method": "recording"}


class MusicBrainzGraphTest(unittest.TestCase):
    def test_unique_profiles_explanations_and_coverage(self):
        cache = {"artists": {
            "A": match(1, {"shoegaze": 4, "rock": 1, "ignored": 0}),
            "Alias A": match(1, {"shoegaze": 4, "rock": 1}),
            "B": match(2, {"rock": 1, "shoegaze": 4}),
            "C": match(3, {"rock": 4}),
            "No genres": match(4, {}),
            "Outside history": match(5, {"rock": 4}),
        }}
        times = {"A": 50, "Alias A": 25, "B": 100, "C": 45, "No genres": 17, "Unmatched": 20, "": 32}
        edges, stats = graph(cache, times)
        self.assertEqual(edges, [["A", "B", ["shoegaze", "rock"], 1]])
        self.assertEqual(stats, {
            "totalCredits": 6, "totalMs": 289, "namedMs": 257,
            "matchedCredits": 5, "matchedMs": 237, "matchedMbids": 4,
            "taggedCredits": 4, "taggedMs": 220, "taggedMbids": 3,
            "linkedCredits": 2, "linkedMs": 150, "linkedMbids": 2, "edgeCount": 1,
        })
        self.assertEqual(graph(cache, dict(reversed(times.items()))), (edges, stats))

    def test_sparse_ties_rare_and_broad_single_tags(self):
        artists = {str(i): match(i, {"pop": 1, "rock": 1}) for i in range(1, 6)}
        artists.update({"a": match(6, {"zeuhl": 1}), "b": match(7, {"zeuhl": 1}),
                        "c": match(8, {"jazz": 1}), "d": match(9, {"jazz": 1})})
        edges, _ = graph({"artists": artists}, dict.fromkeys(artists, 1))
        self.assertEqual(edges, [["a", "b", ["zeuhl"], 1]])

    def test_import_preserves_tracks_and_uses_musicbrainz(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source = base / "Apple Music - Play History Daily Tracks.csv"
            with source.open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["Media type", "Track Identifier", "Date Played", "Play Duration Milliseconds",
                                 "Track Description"])
                for index, name in enumerate(["a", "b"]):
                    writer.writerow(["AUDIO", index + 1, "20250101", 200, f"{name} - Song"])
            cache = base / "match.json"
            cache.write_text(json.dumps({"artists": {name: match(i, {"dream pop": 1})
                                                     for i, name in enumerate(["a", "b"], 1)}}))
            output = base / "history.json"
            cmd = [sys.executable, str(SCRIPTS / "import-music.py"), folder, "--output", str(output)]
            subprocess.run(cmd, check=True, capture_output=True)
            previous = json.loads(output.read_text())
            subprocess.run([*cmd, "--musicbrainz", str(cache)], check=True, capture_output=True)
            current = json.loads(output.read_text())
            expected = [{**track, "group": "Pop"} for track in previous["tracks"]]
            self.assertEqual(current["tracks"], expected)
            self.assertEqual(current["relation"], "musicbrainz")
            self.assertEqual(current["coverage"]["musicbrainz"]["linkedMs"], 400)
            self.assertEqual(current["edges"], [["a", "b", ["dream pop"], 1]])


if __name__ == "__main__":
    unittest.main()
