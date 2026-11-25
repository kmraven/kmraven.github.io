import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from music_artists import assign_primary_artists, canonicalize, possible_lead_names


class ArtistIdentityTest(unittest.TestCase):
    def test_catalog_spelling_and_feature_without_space_supply_leads(self):
        rows = [{"id": "1", "artist": "Akiko Yano & Soichi Noguchi"},
                {"id": "2", "artist": "m-flo feat.Towa Tei,Bahamadia & Chops"}]
        assign_primary_artists(rows, {}, member_names=["akiko yano"])
        self.assertEqual([r["artist"] for r in rows], ["Akiko Yano", "m-flo"])

    def test_credits_go_to_one_lead_and_keep_original_text(self):
        names = ["STUTS", "Mirage Collective, STUTS, butaji & YONCE", "STUTS×Guest",
                 "初参加、共演者", "新顔 (feat. Guest)", "未知 & 不明", "STUTS & 不明",
                 "Earth, Wind & Fire", "Fear, and Loathing in Las Vegas", "Earth", "Fear",
                 "Earth, Wind & Fire & Guest", "Known & Band", "Known",
                 "Lilly Wood & The Prick and Robin Schulz", "MAN WITH A MISSION & Guest",
                 "MAN WITH A MISSION", "Au/Ra & Guest", "Au/Ra", "X & STUTS"]
        rows = [{"artist": n, "id": str(i), "years": {"2020": 100 + i}} for i, n in enumerate(names)]
        matches = {"Known & Band": {"mbid": "intact"}}
        assign_primary_artists(rows, matches, artist_names=["Lilly Wood & The Prick"])
        expected = ["STUTS", "Mirage Collective", "STUTS", "初参加", "新顔", "未知 & 不明",
                    "STUTS", "Earth, Wind & Fire", "Fear, and Loathing in Las Vegas", "Earth", "Fear",
                    "Earth, Wind & Fire", "Known & Band", "Known", "Lilly Wood & The Prick",
                    "MAN WITH A MISSION", "MAN WITH A MISSION", "Au/Ra", "Au/Ra", "X"]
        self.assertEqual([r["artist"] for r in rows], expected)
        self.assertEqual([r.get("credit") for r in rows],
                         [old if old != new else None for old, new in zip(names, expected)])
        self.assertEqual([r["years"]["2020"] for r in rows], list(range(100, 120)))

    def test_exact_track_apple_artist_supplies_an_otherwise_unidentified_lead(self):
        names = ["初参加 & 共演者", "初参加 & 共演者", "ソロ", "Primary & Second", "Unknown & Guest",
                 "Unlisted & Uncredited"]
        rows = [{"artist": name, "id": str(i)} for i, name in enumerate(names)]
        catalog = {"0": {"artist": "First", "artistId": "10"}, "2": {"artist": "Solo"},
                   "3": {"artist": "Second", "artistId": "11"},
                   "4": {"artist": "Unknown & Guest", "artistId": "12"},
                   "5": {"artist": "Various Artists", "artistId": "1"}}
        assign_primary_artists(rows, {}, catalog)
        self.assertEqual([r["artist"] for r in rows],
                         ["First", "初参加 & 共演者", "ソロ", "Primary", "Unknown & Guest",
                          "Unlisted & Uncredited"])

    def test_candidate_prefixes_include_an_intact_band_inside_a_joint_credit(self):
        self.assertIn("Fear, and Loathing in Las Vegas",
                      possible_lead_names("Fear, and Loathing in Las Vegas × Guest"))

    def test_full_credit_used_as_a_solo_artists_database_alias_still_has_a_lead(self):
        rows = [{"artist": "Dillon Francis & DJ Snake", "id": "99"}]
        matches = {"Dillon Francis & DJ Snake": {"mbid": "dillon", "aliases": ["Dillon Francis"]}}
        assign_primary_artists(rows, matches)
        self.assertEqual(rows[0]["artist"], "Dillon Francis")
        self.assertEqual(rows[0]["credit"], "Dillon Francis & DJ Snake")

    def test_lead_remains_a_complete_artist_including_qualifiers_and_initials(self):
        names = ["RY X & Guest", "4*TOWN (From Disney and Pixar), Guest",
                 "μ's(ことり、海未)", "Guest", "SOIL&“PIMP”SESSIONS & Guest", "Au/Ra & Guest"]
        rows = [{"id": str(i), "artist": name} for i, name in enumerate(names)]
        assign_primary_artists(rows, {})
        self.assertEqual([r["artist"] for r in rows], ["RY X", "4*TOWN (From Disney and Pixar)",
                         "μ's(ことり、海未)", "Guest", "SOIL&“PIMP”SESSIONS", "Au/Ra"])

    def test_verified_credits_share_an_artist_but_homonyms_remain_separate(self):
        rows = [
            {"artist": label, "id": str(i), "group": group, "years": {"2020": ms}}
            for i, (label, group, ms) in enumerate([
                ("Band", "", 900), ("バンド", "Rock", 250), ("BAND", "Pop", 500),
                ("Guest", "Rock", 11), ("バンド & Guest", "", 12),
                ("BAND & Guest", "", 25), ("バンド & Unknown", "", 16),
            ])
        ]
        matches = {"artists": {
            "Band": {"mbid": "one", "aliases": ["バンド"], "tags": {"rock": 1}},
            "バンド": {"mbid": "one", "tags": {"rock": 1}},
            "BAND": {"mbid": "different", "tags": {"pop": 2}},
            "Guest": {"mbid": "guest", "tags": {"rock": 1}},
        }}
        profiles, aliases = canonicalize(rows, matches)
        self.assertEqual([r["artist"] for r in rows[:3]], ["Band", "Band", "BAND"])
        self.assertEqual([r["group"] for r in rows[:3]], ["Rock", "Rock", "Pop"])
        self.assertEqual(aliases["Band"], ["バンド"])
        self.assertEqual(profiles["artists"]["Band"]["mbid"], "one")
        self.assertEqual(sum(r["years"]["2020"] for r in rows), 1714)
