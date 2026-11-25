import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import music_genre_sources as sources


ARTIST = "aaaaaaaa-1111-4444-8888-bbbbbbbbbbbb"


class GenreSourcesTest(unittest.TestCase):
    def test_only_public_ids_sent_and_unusable_results_excluded(self):
        calls = []

        def response(request, timeout):
            calls.append(request)
            if request.data:
                item = "http://www.wikidata.org/entity/"
                value = {"mb": {"value": ARTIST}, "artist": {"value": item + "Q1"},
                         "genre": {"value": item + "Q2"}}
                payload = {"results": {"bindings": [value]}}
            else:
                rows = [{"wrapperType": "track", "kind": "song", "trackId": i,
                         "primaryGenreName": g} for i, g in [(11, "Pop"), (12, "Other")]]
                payload = {"resultCount": len(rows), "results": rows}
            return io.BytesIO(json.dumps(payload).encode())

        with tempfile.TemporaryDirectory() as folder, patch.object(sources, "urlopen", side_effect=response):
            path = Path(folder) / "sources.json"
            ids = ["1", "11", "12", "Private Title", "-4", "３"]
            result = sources.refresh_sources(path, ids, [ARTIST])
            self.assertEqual(result["appleNoSpecificGenre"], ["12"])
            self.assertEqual(set(result["appleTracks"]), {"11"})
            self.assertEqual(result["wikidataByMusicBrainzArtistId"][ARTIST], {"Q1": {"Q2": "Q2"}})
            self.assertTrue(any(ARTIST in parse_qs(c.data.decode())["query"][0] for c in calls if c.data))
            ids_sent = [parse_qs(urlsplit(c.full_url).query) for c in calls if not c.data]
            self.assertEqual(ids_sent, [{"id": ["11,12"], "country": ["JP"], "lang": ["en_us"], "limit": ["200"]}])
            self.assertEqual(sources.refresh_sources(path, ids, [ARTIST]), result)
            self.assertEqual(len(calls), 2)

    def test_retry_leaves_completed_batches_and_retries_only_pending_ids(self):
        limited = HTTPError("https://itunes.apple.com/lookup", 429, "", {"Retry-After": "720"}, None)
        with tempfile.TemporaryDirectory() as folder, patch.object(sources.time, "sleep"):
            path = Path(folder) / "sources.json"
            ids = set(range(10, 191))
            with patch.object(sources, "_apple", side_effect=[{}, limited]) as fetch:
                with self.assertRaisesRegex(sources.GenreRefreshError, "429") as error:
                    sources.refresh_sources(path, ids, [])
                self.assertGreater(error.exception.retry_at, time.time() + 719)
                self.assertEqual(fetch.call_count, 2)
            stored = json.loads(path.read_text())
            self.assertEqual(len(stored["appleNoSpecificGenre"]), 180)
            with patch.object(sources, "_apple", return_value={}) as fetch:
                with self.assertRaisesRegex(OSError, "requested a retry"):
                    sources.refresh_sources(path, ids, [])
                fetch.assert_not_called()
                with patch.object(sources.time, "time", return_value=time.time() + 721):
                    sources.refresh_sources(path, ids, [])
                fetch.assert_called_once_with(sorted(set(map(str, ids)) - set(stored["appleNoSpecificGenre"])))

    def test_successful_refresh_updates_hits_and_misses(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(sources.time, "sleep"):
            path = Path(folder) / "sources.json"
            with patch.object(sources, "_apple", return_value={"10": {"primaryGenreName": "Pop"}}):
                sources.refresh_sources(path, [10, 20], [])
            with patch.object(sources, "_apple", return_value={"20": {"primaryGenreName": "Jazz"}}):
                result = sources.refresh_sources(path, [10, 20], [], refresh=True)
            self.assertEqual(result["appleNoSpecificGenre"], ["10"])
            self.assertEqual(result["appleTracks"], {"20": {"primaryGenreName": "Jazz"}})


if __name__ == "__main__":
    unittest.main()
