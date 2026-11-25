import io
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import musicbrainz_match as matcher
from musicbrainz_recordings import recording_index


class MusicBrainzMatchTest(unittest.TestCase):
    def test_registered_joint_spelling_can_have_a_separately_credited_recording(self):
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE TABLE credit_recordings(mbid, title, credit)")
            db.execute("INSERT INTO credit_recordings VALUES ('lead', '別題', 'first & second')")
            tracks = [{"id": "1", "artist": "First & Second", "title": "Title", "titleAliases": ["別題"]},
                      {"id": "2", "artist": "First & Second", "title": "Different recording"}]
            found = matcher.joint_recording_leads(tracks, {}, {"lead": {"names": ["first"]}}, db)
            self.assertEqual(found, {"1": {"credit": "First & Second", "lead": "First"}})
            self.assertFalse(matcher.joint_recording_leads(tracks, {"First & Second": {}},
                                                          {"lead": {"names": ["first"]}}, db))

    def test_search_aliases_are_current_preferred_artist_names(self):
        preferred = {"type": "Artist name", "primary": True, "locale": "en"}
        artist = {"name": "山田花子", "sort-name": "Yamada, Hanako", "aliases": [
            dict(preferred, name="Hanako Yamada"),
            dict(preferred, name="Ｈａｎａｋｏ Ｙａｍａｄａ"),
            dict(preferred, name="ヤマダハナコ", locale="ja_Kana", **{"sort-name": "ヤマダ, ハナコ"}),
            dict(preferred, name="Former Name", ended=True),
            dict(preferred, name="Another Project", primary=False),
            dict(preferred, name="Legal Name", type="Legal name"),
            dict(preferred, name="Yamada, Hanako", type="Search hint"),
            dict(preferred, name="Unspecified", type=None),
            dict(preferred, name="Other Locale", locale="fr"),
        ]}
        self.assertEqual(matcher.search_aliases(artist), ["山田花子", "Hanako Yamada", "ヤマダハナコ"])

    @unittest.skipUnless(shutil.which("zstd"), "requires the catalog decompressor")
    def test_canonical_index_streams_unicode_and_preserves_previous_db_on_error(self):
        mbid = "12345678-1234-1234-1234-123456789abc"
        title = "ＳＯＮＧ\r\n日本語"
        csv = (f'artist_mbids,recording_name,recording_mbid\r\n{mbid},"{title}",R1\r\n'
               f'{mbid};{mbid},"{title}",duet\r\n{mbid},別の曲名,R2\r\n').encode()
        history = {"tracks": [{"title": "song 日本語"}]}

        def compress(member_name):
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode="w") as archive:
                member = tarfile.TarInfo(member_name)
                member.size = len(csv)
                archive.addfile(member, io.BytesIO(csv))
            return subprocess.check_output(["zstd", "-qc"], input=stream.getvalue())

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            archive = folder / "canonical.tar.zst"
            database = folder / "recordings.sqlite"
            compressed = compress("dump/canonical_musicbrainz_data.csv")
            archive.write_bytes(compressed)
            recording_index(archive, history, database)
            with sqlite3.connect(database) as db:
                self.assertEqual(db.execute("SELECT mbid, title FROM credit_recordings").fetchall(), [(mbid, title)])
            history["tracks"][0]["titleAliases"] = ["別の曲名"]
            recording_index(archive, history, database)
            with sqlite3.connect(database) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM credit_recordings").fetchone(), (2,))
                rows = db.execute("SELECT title, recording_mbid FROM credit_recordings").fetchall()
                self.assertEqual(set(rows), {(title, "R1"), ("別の曲名", "R2")})
            before = database.read_bytes()
            archive.write_bytes(compress("dump/irrelevant.csv"))
            with self.assertRaises(ValueError):
                recording_index(archive, history, database)
            self.assertEqual(database.read_bytes(), before)
            for partial in (compressed[:len(compressed) // 2], compressed[:-1]):
                archive.write_bytes(partial)
                with self.assertRaises((tarfile.TarError, ValueError)):
                    recording_index(archive, history, database)
                self.assertEqual(database.read_bytes(), before)

    def test_matches_apple_ids_and_recordings_without_guessing_homonyms(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            archive = folder / "artist.tar.xz"
            library = "Apple Music Library Artists.json"
            with ZipFile(folder / (library + ".zip"), "w") as z:
                z.writestr(library, json.dumps([
                    {"Artist Name": "Localized", "Catalog Identifiers - Artist": "123"},
                    {"Artist Name": "Group & Guest", "Catalog Identifiers - Artist": "456"},
                ]))
            artists = [
                ("A", "Untranslated", [], "123"), ("B", "Group", [], "456"),
                ("C", "Artist", ["Alias"], ""), ("D", "Homonym", [], ""),
                ("E", "Homonym", [], ""), ("F", "New Name", [], ""),
            ]
            rows = []
            for mbid, name, aliases, apple in artists:
                rows.append({
                    "id": mbid, "name": name, "aliases": [{"name": a} for a in aliases],
                    "relations": [{"url": {"resource": f"https://music.apple.com/jp/artist/name/{apple}"}}],
                    "genres": [{"name": "ambient", "count": 2}, {"name": "jazz", "count": 0}] if mbid != "A" else [],
                    "tags": [{"name": "my favorite", "count": 100}],
                })
            buf = ("\n".join(map(json.dumps, rows)) + "\n").encode()
            with tarfile.open(archive, "w:xz") as tar:
                member = tarfile.TarInfo("mbdump/artist")
                member.size = len(buf)
                tar.addfile(member, io.BytesIO(buf))
            history = {"tracks": [{"artist": credit, "title": title} for credit, title in [
                ("Localized", "Song"), ("Group & Guest", "Duet"), ("ＡＬＩＡＳ", "ＳＯＮＧ"),
                ("Homonym", "First Match"), ("LOCALIZED", "Unrelated song"),
            ]]}
            db_path = folder / "recordings.sqlite"
            with sqlite3.connect(db_path) as db:
                db.execute("CREATE TABLE credit_recordings (mbid, title)")
                db.executemany("INSERT INTO credit_recordings VALUES (?, ?)", [
                    ("C", "Song"), ("D", "First Match"), ("D", "Second Match"), ("E", "Other Work"),
                    ("F", "New Song"), ("A", "Verified Piece"),
                ])
            output = folder / "matches.json"

            def run(db=db_path):
                result = matcher.match(archive, folder, history, db, output)
                self.assertEqual(json.loads(output.read_text()), result)
                return result["artists"]

            self.assertEqual(run(None), {"Localized": {
                "mbid": "A", "method": "apple-id", "tags": {}, "aliases": ["Untranslated"]
            }})
            with patch.object(matcher, "scan_artists", side_effect=AssertionError("Unnecessary rescan")):
                resolved = run()
                self.assertEqual(set(resolved), {"Localized", "ＡＬＩＡＳ"})
                self.assertEqual(resolved["ＡＬＩＡＳ"], {
                    "mbid": "C", "method": "name+recording", "tags": {"ambient": 2}, "aliases": ["Artist"]
                })
                history["tracks"].append({"artist": "LOCALIZED", "title": "Verified Piece"})
                self.assertEqual(run()["LOCALIZED"]["method"], "name+recording")
                history["tracks"].append({"artist": "Homonym", "title": "Second Match"})
                self.assertEqual(run()["Homonym"]["mbid"], "D")
                history["tracks"].append({"artist": "Homonym", "title": "Other Work"})
                self.assertNotIn("Homonym", run())
            history["tracks"].append({"artist": "New Name", "title": "New Song"})
            self.assertEqual(run()["New Name"]["mbid"], "F")

    def test_localized_titles_need_independent_tracks_and_recordings_for_homonyms(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            output = folder / "matches.json"
            db_path = folder / "recordings.sqlite"
            candidates = {i: {"names": ["same"], "apple": [], "tags": {}, "aliases": ["Same"]}
                          for i in ("A", "B")}
            with sqlite3.connect(db_path) as db:
                db.execute("CREATE TABLE credit_recordings (mbid, title, recording_mbid)")
                db.executemany("INSERT INTO credit_recordings VALUES (?, ?, ?)", [
                    ("A", "First song", "R1"), ("A", "第一曲", "R1"), ("A", "Second song", "R2"),
                    ("B", "Third song", "R3"),
                ])

            def match(*tracks):
                history = {"tracks": [dict(artist="Same", **track) for track in tracks]}
                with patch.object(matcher, "candidates_for", return_value=candidates):
                    return matcher.match(folder, folder, history, db_path, output)["artists"]

            first = {"id": "1", "title": "第一曲", "titleAliases": ["First song"]}
            second = {"id": "2", "title": "第二曲", "titleAliases": ["Second song"]}
            self.assertEqual(match(first, second).get("Same", {}).get("mbid"), "A")
            self.assertEqual(match(first), {})
            self.assertEqual(match(first, dict(second, id="1")), {})
            self.assertEqual(match(dict(first, titleAliases=[]), {"id": "2", "title": "First song"}), {})
            self.assertEqual(match(first, second, {"id": "3", "title": "第三曲", "titleAliases": ["Third song"]}), {})

    @unittest.skipUnless(shutil.which("zstd"), "requires the catalog decompressor")
    def test_joint_recordings_require_the_source_credit_title_and_participating_artist(self):
        lead = "00000000-0000-0000-0000-000000000001"
        guest = "00000000-0000-0000-0000-000000000002"
        homonym = "00000000-0000-0000-0000-000000000003"
        candidates = {
            identity: {"names": [name.lower()], "aliases": [name], "tags": {}, "apple": []}
            for identity, name in [(lead, "Lead"), (guest, "Guest"), (homonym, "Lead")]
        }
        apple = [
            {"id": "1", "artist": "Lead & Guest", "title": "第一曲", "titleAliases": ["First song"]},
            {"id": "2", "artist": "Lead & Guest", "title": "Second song"},
            {"id": "3", "artist": "Guest", "title": "First song"},
            {"id": "4", "artist": "Lead & Other", "title": "Second song"},
        ]
        data = ('artist_mbids,artist_credit_name,recording_name,recording_mbid\n'
                f'"{lead},{guest}",LEAD & GUEST,First song,R1\n'
                f'"{lead},{guest}",LEAD & GUEST,Second song,R2\n'
                f'"{homonym},{guest}",Different & Guest,First song,R3\n').encode()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            database, archive = folder / "index.sqlite", folder / "canonical.tar.zst"
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode="w") as tar:
                member = tarfile.TarInfo("canonical_musicbrainz_data.csv")
                member.size = len(data)
                tar.addfile(member, io.BytesIO(data))
            archive.write_bytes(subprocess.check_output(["zstd", "-qc"], input=stream.getvalue()))
            recording_index(archive, {"tracks": apple}, database)

            def resolve(*rows):
                history = {"tracks": [r.copy() for r in rows]}
                with patch.object(matcher, "candidates_for", return_value=candidates):
                    return matcher.match(archive, folder, history, database, folder / "matches.json",
                                         lead_catalog={})["artists"]

            matched = resolve(*apple)
            self.assertEqual({name: info["mbid"] for name, info in matched.items()}, {"Lead": lead})
            self.assertEqual(resolve(apple[0], apple[2], apple[3]), {})
            self.assertEqual(resolve(apple[0], dict(apple[1], id="1")), {})


if __name__ == "__main__":
    unittest.main()
