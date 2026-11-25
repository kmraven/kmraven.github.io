import json
from pathlib import Path
import runpy
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit


catalog = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/music-catalog.py"))


class MusicCatalogTest(unittest.TestCase):
    def test_skips_missing_song_in_a_batch_that_returns_404(self):
        attempts = []
        cache = {"tracks": {}, "similar": {}}

        def fetch(path):
            url = urlsplit(path)
            if not url.path.endswith("/songs"):
                return {"data": []}
            ids = parse_qs(url.query)["ids"][0].split(",")
            attempts.append(ids)
            if "102" in ids:
                raise catalog["MissingResource"]("Synthetic 404")
            return {"data": [{
                "type": "songs", "id": track,
                "attributes": {"name": "Song", "artistName": "Artist"},
                "relationships": {"artists": {"data": [{"id": "50", "type": "artists"}]}},
            } for track in ids]}

        ids = {"101", "102", "103", "104"}
        catalog["enrich"](ids, "jp", cache, fetch, lambda: None)
        self.assertEqual(set(cache["tracks"]), {"101", "103", "104"})
        self.assertEqual(cache["similar"], {"50": []})
        self.assertIn(["103", "104"], attempts)
        attempts.clear()
        catalog["enrich"](ids, "jp", cache, fetch, lambda: None)
        self.assertEqual(attempts, [["102"]])

    def test_resumes_without_recording_a_partially_fetched_artist(self):
        song = {
            "id": "123", "type": "songs",
            "attributes": {"artistName": "Artist and guest", "name": "Song", "genreNames": ["Jazz"]},
            "relationships": {"artists": {"data": [
                {"id": "456", "type": "artists", "attributes": {"name": "Artist"}}
            ]}},
        }
        cache = {"tracks": {}, "similar": {}}
        calls = []

        def fetch(path):
            url = urlsplit(path)
            calls.append(url)
            if url.path.endswith("/songs"):
                self.assertEqual(parse_qs(url.query)["include"], ["artists"])
                return {"data": [song] if "123" in parse_qs(url.query)["ids"][0].split(",") else []}
            self.assertEqual(url.path, "/v1/catalog/jp/artists/456/view/similar-artists")
            if not url.query:
                return {"data": [{"type": "artists", "id": "789"}], "next": "?offset=1"}
            if len(calls) == 3:
                raise catalog["CatalogError"]("Synthetic outage")
            return {"data": [{"type": "artists", "id": "987"}]}

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "daily.csv"
            source.write_text("Track Identifier,Media type\n123,AUDIO\n124,AUDIO\n125,VIDEO\nN/A,AUDIO\n")
            ids = catalog["audio_track_ids"](source)
            self.assertEqual(ids, {"123", "124"})
            with self.assertRaises(catalog["CatalogError"]):
                catalog["enrich"](ids, "jp", cache, fetch, lambda: None)
            self.assertEqual(cache, {"tracks": {"123": {
                "artist": "Artist", "artistId": "456", "genre": "Jazz", "title": "Song"
            }}, "similar": {}})
            catalog["enrich"](ids, "jp", cache, fetch, lambda: None)
            self.assertEqual(parse_qs(calls[3].query)["ids"], ["124"])
            self.assertEqual(cache["similar"], {"456": ["789", "987"]})
            path = Path(directory) / "cache.json"
            catalog["save_cache"](path, cache)
            self.assertEqual(json.loads(path.read_text()), cache)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
