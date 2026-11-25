import csv
import json
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from zipfile import ZipFile


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import_music = runpy.run_path(str(SCRIPTS / "import-music.py"))


class TrackTitleTest(unittest.TestCase):
    def test_export_titles_stay_with_their_store_track(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with (folder / import_music["DAILY_FILE"]).open("w") as stream:
                writer = csv.writer(stream)
                writer.writerow(["Media type", "Track Identifier", "Date Played", "Play Duration Milliseconds",
                                 "Track Description"])
                writer.writerows([["AUDIO", "101", "2025-02-03", "200", "First & Guest - English Title"],
                                  ["AUDIO", "102", "2025-02-03", "100", "First - Other Song"]])
            with ZipFile(folder / "Identifier Information.json.zip", "w") as archive:
                archive.writestr("Identifier Information.json", json.dumps([
                    {"Identifier": "101", "Title": "邦題"}, {"Identifier": "103", "Title": "別の録音"}]))
            with (folder / import_music["FAVORITES"]).open("w") as stream:
                writer = csv.writer(stream)
                writer.writerow(["Favorite Type", "Item Reference", "Item Description", "Last Modified", "Preference"])
                writer.writerows([["Song", "101", "First & Guest - Another Title", "2025-01-01", "LIKE"],
                                  ["Album", "102", "First - Unrelated Album", "2025-01-01", "LIKE"],
                                  ["Song", "102", "First - Other Song", "2025-02-01", "NEUTRAL"],
                                  ["Song", "102", "First - Other Song", "2025-01-01", "LIKE"],
                                  ["Artist", "201", "First", "2025-01-01", "LIKE"]])
            result = import_music["build"](folder, {})
            self.assertEqual(result["favorites"], {"artists": ["First"], "tracks": ["101"]})
            rows = result["tracks"]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0], {"id": "101", "artist": "First", "credit": "First & Guest",
                                      "title": "English Title", "titleAliases": ["Another Title", "邦題"],
                                      "group": "", "years": {"2025": 200}})
            self.assertNotIn("titleAliases", rows[1])
            self.assertNotIn("credit", rows[1])
