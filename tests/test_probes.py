"""Probes must use observed evidence without revealing the answer to the agent."""
import json
import unittest

from benchmark.probes import build_probes, public_probe, check_answer


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.trace = [
            {"observation": {"room": "Убежище", "exits": ["east"], "message": "Начало"},
             "action": {"type": "move", "direction": "east"}},
            {"observation": {"room": "Кузница", "exits": ["west", "east"],
                 "message": "Альма: найдите медный компас в месте «Склеп» и принесите мне сюда, в «Кузница». Я не повторю поручение."},
             "action": {"type": "move", "direction": "east"}},
        ]
        self.final = {"room": "Сад", "message": "Вы перешли в другую комнату.", "exits": ["west"]}

    def test_builds_answerable_probes_and_hides_answers(self):
        probes = build_probes(self.trace, self.final)
        by_capability = {p["capability"]: p for p in probes}
        self.assertEqual(by_capability["quest_memory"]["answer"], "Склеп")
        self.assertEqual(by_capability["navigation_recall"]["answer"], "Кузница")
        for probe in probes:
            public = public_probe(probe)
            self.assertEqual(set(public), {"id", "question"})
            self.assertNotIn(probe["answer"], json.dumps(public, ensure_ascii=False))
            self.assertNotIn(probe["answer"], json.dumps(self.final, ensure_ascii=False))
            self.assertTrue(check_answer(probe, probe["answer"]))
            self.assertFalse(check_answer(probe, "не знаю"))
        self.assertTrue(check_answer(by_capability["quest_memory"], "  «СКЛЕП»  "))

    def test_no_probe_when_current_observation_reveals_the_answer(self):
        final = {"room": "Кузница", "message": "В инвентаре Склеп", "exits": ["west"]}
        for probe in build_probes(self.trace, final):
            self.assertNotIn(probe["answer"], json.dumps(final, ensure_ascii=False))

    def test_invalid_move_does_not_become_spatial_question(self):
        trace = [{"observation": {"room": "Дом", "exits": ["east"]},
                  "action": {"type": "move", "direction": "west"}}]
        self.assertEqual(build_probes(trace, {"room": "Дом"}), [])

    def test_invalid_limit_rejected(self):
        with self.assertRaises(ValueError):
            build_probes([], {}, max_per_capability=-1)


if __name__ == "__main__":
    unittest.main()
