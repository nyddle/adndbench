"""Runner integration and API contract without external network access."""
import io
import json
import unittest
from unittest.mock import patch

from benchmark.runner import BaselineAgent, OpenAICompatibleAgent, run_episode


class ProbeBaseline(BaselineAgent):
    def __init__(self):
        super().__init__()
        self.questions = []

    def answer_probe(self, observation, question):
        self.questions.append((observation, question))
        return "не знаю"


class RunnerTests(unittest.TestCase):
    def test_baseline_is_reproducible_and_can_complete(self):
        first = run_episode(1, BaselineAgent(), max_turns=120)
        second = run_episode(1, BaselineAgent(), max_turns=120)
        self.assertEqual(first, second)
        self.assertEqual(first["result"]["terminal_reason"], "completed")
        self.assertEqual(first["score"]["outcomes"]["actions"]["invalid"], 0)

    def test_probe_scores_are_computed_without_sending_answer_key(self):
        agent = ProbeBaseline()
        run = run_episode(1, agent, max_turns=120)
        self.assertGreater(len(agent.questions), 0)
        self.assertEqual(len(agent.questions), len(run["probes"]))
        for (observation, public), evaluated in zip(agent.questions, run["probes"]):
            self.assertEqual(set(public), {"id", "question"})
            self.assertNotIn(evaluated["answer"], json.dumps(public, ensure_ascii=False))
            # A compass direction in the current room's exits is not the
            # relative direction of the two rooms in a reasoning question.
            if evaluated["capability"] != "spatial_reasoning":
                self.assertNotIn(evaluated["answer"], json.dumps(observation, ensure_ascii=False))
            self.assertFalse(evaluated["correct"])
        for category, counts in run["result"]["probe_results"].items():
            self.assertEqual(counts["correct"], 0)
            self.assertGreater(counts["total"], 0)
            self.assertEqual(run["score"]["capability_scores"][category], 0)
        self.assertIsNone(run["score"]["capability_scores"]["tactics"])

    def test_openai_adapter_formats_actions_and_independent_probe_request(self):
        requests = []
        responses = [
            {"choices": [{"message": {"content": '{"type":"talk"}'}}]},
            {"choices": [{"message": {"content": '{"id":"q1","answer":"Кузница"}'}}]},
        ]
        def urlopen(request, timeout):
            requests.append(json.loads(request.data))
            return io.BytesIO(json.dumps(responses.pop(0), ensure_ascii=False).encode())
        agent = OpenAICompatibleAgent("test-model", "https://example.test/chat", "fake-key")
        with patch("urllib.request.urlopen", side_effect=urlopen):
            self.assertEqual(agent.act({"room": "Дом"}), {"type": "talk"})
            answer = agent.answer_probe({"room": "Сад"}, {"id": "q1", "question": "Где?"})
        self.assertEqual(answer, "Кузница")
        self.assertEqual(requests[0]["model"], "test-model")
        self.assertEqual(requests[0]["temperature"], 0)
        self.assertIn('"id": "q1"', requests[1]["messages"][-1]["content"])
        self.assertNotIn("Кузница", json.dumps(requests[1], ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
