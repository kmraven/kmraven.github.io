import sys
import unittest
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from music_styles import apply_styles


def groups(genre):
    return {"Hip-Hop/Rap": "Hip-Hop / Rap", "R&B/Soul": "R&B / Soul", "Anime": "Anime / Soundtrack",
            "Music": ""}.get(genre, genre)


class StyleTest(unittest.TestCase):
    def test_exact_entity_evidence_and_distinct_song_distribution(self):
        a, b, c = (str(UUID(int=i)) for i in (1, 2, 3))
        matches = {"artists": {"Aooo": {"mbid": a, "tags": {"j-pop": 1, "rock": 1}},
                               "the HIATUS": {"mbid": b, "tags": {}}, "Yo-Sea": {"mbid": c}}}
        rows = [{"artist": "Aooo", "id": "a"}, {"artist": "the HIATUS", "id": "b"},
                *({"artist": "Yo-Sea", "id": str(i)} for i in range(10)),
                {"artist": "Yo-Sea", "id": "9"}, {"artist": "", "id": "f", "group": "Jazz"}]
        source = {"wikidataByMusicBrainzArtistId": {
            a: {"Q1": {"Q4": "rock music"}}, b: {"Q2": {"Q6": "progressive rock", "Q5": "alternative rock"}},
            c: {"Q3": {"Q5": "alternative rock"}, "Q4": {"Q5": "alternative rock"}}},
            "appleTracks": {**{str(i): {"primaryGenreName": "R&B/Soul" if i < 9 else "Hip-Hop/Rap"}
                               for i in range(10)}, "a": {"primaryGenreName": "J-Pop"}, "f": {"primaryGenreName": "Jazz"}}}
        info, enriched = apply_styles(rows, matches, source, groups, {})
        self.assertEqual((rows[0]["group"], rows[0]["appleGenre"]), ("Rock", "J-Pop"))
        self.assertEqual(enriched["artists"]["Aooo"]["tags"], {"rock": 1, "j-pop": 1})
        self.assertEqual(info["the HIATUS"]["tags"]["wikidata"], ["alternative rock", "progressive rock"])
        self.assertEqual(info["Yo-Sea"]["appleGenres"], {"R&B/Soul": 9, "Hip-Hop/Rap": 1})
        self.assertEqual((rows[4]["group"], info["Yo-Sea"]["method"]), ("R&B / Soul", "apple-tracks"))
        self.assertNotIn("qid", info["Yo-Sea"])
        self.assertNotIn("", info)
        self.assertEqual(rows[-1]["group"], "")

    def test_official_identity_requires_an_exact_bridge(self):
        band = "TOGENASHI TOGEARI"
        mbid = "d2beaa40-4a5f-44b7-a1c9-b12352bf4abf"
        matches = {"artists": {}, "profilesByMbid": {mbid: {"tags": {"j-rock": 2, "alternative rock": 1}}}}
        rows = [{"artist": band, "id": "1"}, {"artist": "Guest", "id": "2"}]
        apple = {"primaryGenreName": "Anime", "artistId": 1688539273}
        source = {"appleTracks": {"1": apple, "2": apple}}
        info, enriched = apply_styles(rows, matches, source, groups, {})
        self.assertEqual((rows[0]["group"], rows[0]["appleGenre"]), ("Rock", "Anime"))
        self.assertEqual(info[band]["tags"]["official"], ["rock"])
        self.assertEqual(enriched["artists"][band], {"mbid": mbid, "tags": {"rock": 1, "j-rock": 2, "alternative rock": 1}})
        self.assertNotIn("mbid", info["Guest"])
        source["appleTracks"]["1"] = {**apple, "artistId": 999}
        info, _ = apply_styles(rows, matches, source, groups, {})
        self.assertNotIn("mbid", info[band])

    def test_recorded_zero_durations_never_outvote_listened_tracks(self):
        rows = [{"artist": "A", "id": "1", "years": {"2020": 1}},
                {"artist": "A", "id": "2", "years": {"2020": 0}},
                {"artist": "A", "id": "3", "years": {"2021": 0}},
                {"artist": "B", "id": "4", "years": {"2021": 0}}]
        source = {"appleTracks": {str(i): {"primaryGenreName": "Rock" if i == 1 else "Anime"}
                                  for i in range(1, 5)}}
        info, _ = apply_styles(rows, {}, source, groups, {})
        self.assertEqual(info["A"]["appleGenres"], {"Rock": 1})
        self.assertNotIn("zeroDurationOnly", info["A"])
        self.assertEqual([r["group"] for r in rows], ["Rock", "Rock", "Rock", "Anime / Soundtrack"])
        self.assertEqual(rows[1]["appleGenre"], "Anime")
        self.assertEqual(info["B"]["appleGenres"], {"Anime": 1})
        self.assertTrue(info["B"]["zeroDurationOnly"])

    def test_synonyms_uninformative_labels_and_conflicts(self):
        mid = str(UUID(int=1))
        matches = {"artists": {"Band": {"mbid": mid, "tags": {
            "UK hip-hop": 2, "other": 4, "Music": 40, "soundtrack": 5}}}}
        source = {"wikidataByMusicBrainzArtistId": {mid: {"Q1": {
            "Q5": "British hip hop", "Q6": "popular music", "Q7": "Q123"}}}}
        rows = [{"artist": "Band", "id": "1"}]
        info, graph = apply_styles(rows, matches, source, groups, {})
        self.assertEqual(graph["artists"]["Band"]["tags"], {"uk hip hop": 2})
        self.assertIn("soundtrack", info["Band"]["tags"]["musicbrainz"])
        matches["artists"]["Band"]["tags"] = {"jazz": 1, "rock": 1}
        source = {"appleTracks": {"1": {"primaryGenreName": "Anime"}}}
        info, _ = apply_styles(rows, matches, source, groups, {"Band": "Anime / Soundtrack"})
        self.assertEqual((rows[0]["group"], info["Band"]["method"]), ("", "unresolved"))
        source["appleTracks"]["1"]["primaryGenreName"] = "Jazz"
        info, _ = apply_styles(rows, matches, source, groups, {})
        self.assertEqual((rows[0]["group"], info["Band"]["method"]), ("Jazz", "style"))
        info, _ = apply_styles(rows, {}, {}, groups, {"Band": "Folk"})
        self.assertEqual((rows[0]["group"], info["Band"]["method"]), ("Folk", "export"))
        self.assertNotIn("appleGenre", rows[0])


if __name__ == "__main__":
    unittest.main()
