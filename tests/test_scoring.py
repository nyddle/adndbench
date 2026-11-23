"""Check outcome calculations and the distinction from ability measurements."""
import unittest

from benchmark.scoring import score


class ScoringTests(unittest.TestCase):
    def test_counts_are_reported_and_rates_calculated(self):
        report = score({
            "seed": 10, "terminal_reason": "limit", "turns": 8,
            "invalid_actions": 2, "quests_completed": 1, "quests_total": 2,
            "rooms_visited": 3, "rooms_total": 4, "moves": 5,
            "attacks": 3, "damage_taken": 7, "potions_used": 1, "deaths": 0,
        })
        self.assertEqual(report["seed"], 10)
        self.assertEqual(report["outcomes"]["quests"]["completion_rate"], 0.5)
        self.assertEqual(report["outcomes"]["exploration"]["coverage"], 0.75)
        self.assertEqual(report["outcomes"]["actions"]["valid_rate"], 0.75)
        self.assertEqual(report["outcomes"]["combat_and_resources"]["damage_taken"], 7)
        self.assertTrue(all(value is None for value in report["capability_scores"].values()))

    def test_missing_or_impossible_denominators_do_not_fabricate_rates(self):
        report = score({"turns": 0, "invalid_actions": 0, "quests_completed": 1,
                        "quests_total": 0, "rooms_visited": 3, "rooms_total": 2})
        self.assertIsNone(report["outcomes"]["quests"]["completion_rate"])
        self.assertIsNone(report["outcomes"]["exploration"]["coverage"])
        self.assertIsNone(report["outcomes"]["actions"]["valid_rate"])

    def test_probe_scores_only_use_valid_counts(self):
        report = score({"probe_results": {
            "quest_memory": {"correct": 2, "total": 3},
            "spatial_reasoning": {"correct": 4, "total": 2},
            "tactics": {"correct": 0, "total": 0},
            "strategy": {"correct": True, "total": 1},
        }})
        self.assertEqual(report["capability_scores"]["quest_memory"], 2 / 3)
        self.assertEqual(report["probe_counts"]["quest_memory"], {"correct": 2, "total": 3})
        for category in ("spatial_reasoning", "tactics", "strategy"):
            self.assertIsNone(report["capability_scores"][category])
            self.assertIsNone(report["probe_counts"][category])

    def test_main_quest_success_is_not_hidden_by_skipped_optional_quest(self):
        report = score({"terminal_reason": "completed", "quests_completed": 1,
                        "quests_total": 2, "main_quest_completed": True,
                        "side_quests_completed": 0, "side_quests_total": 1})
        quests = report["outcomes"]["quests"]
        self.assertTrue(quests["main_completed"])
        self.assertEqual(quests["side_completion_rate"], 0)
        self.assertEqual(quests["completion_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
