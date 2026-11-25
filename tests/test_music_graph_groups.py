from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from music_graph_groups import adjacency, predict, unclassified_reasons


class GraphGroupsTest(unittest.TestCase):
    def test_two_distinct_concordant_seeds_within_two_links(self):
        graph = adjacency([(a, b, [], score) for a, b, score in [
            ("x", "a", .9), ("x", "mid", .8), ("mid", "b", .8),
            ("x", "weak", .59), ("mid", "far", .9), ("far", "c", .95),
            ("a", "beyond-labelled-a", .9)]])
        seeds = {"a": "Rock", "b": "Rock", "weak": "Pop", "c": "Jazz", "beyond-labelled-a": "Jazz"}
        self.assertEqual(predict("x", graph, seeds), {"group": "Rock", "neighbors": ["a", "b"], "method": "tags"})
        self.assertIsNone(predict("x", graph, {**seeds, "b": "Pop"}))
        self.assertIsNone(predict("unconnected", graph, seeds))
        graph["mid"]["a"] = .9
        del seeds["b"]
        self.assertIsNone(predict("x", graph, seeds))

    def test_reasons_distinguish_resolution_from_genre_coverage(self):
        profiles = {"Empty": {"tags": {}}, "Tied": {"tags": {"rock": 2, "jazz": 2}},
                    "Outside": {"tags": {"unmapped": 5, "rock": 1}}}
        credits = ["", "Unknown", "Unverified", *profiles]
        self.assertEqual(unclassified_reasons(credits, profiles, {"id": {"names": ["unverified"]}}),
                         {"": "credit-missing", "Unknown": "no-candidate", "Unverified": "identity-unverified",
                          "Empty": "no-genres", "Tied": "genre-tie", "Outside": "genre-unmapped"})
        self.assertEqual(unclassified_reasons(["Unverified"], profiles), {"Unverified": "no-identity"})
