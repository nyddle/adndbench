import unittest
from benchmark.vector_harness import advance, replay


class CounterGame:
    def __init__(self): self.n = 0
    def observe(self): return {'count': self.n, 'done': self.n >= 2}
    def step(self, action):
        self.n += 1
        return self.observe()
    def result(self): return {'terminal_reason': 'completed' if self.n >= 2 else None}


def allowed(_): return [{'type': 'step'}]


class HarnessTests(unittest.TestCase):
    def test_resume_replays_observations_and_rejects_changed_history(self):
        journal = []
        with self.assertRaises(ConnectionError):
            advance(CounterGame(), journal,
                    lambda history, obs: {'type': 'step'} if not history else (_ for _ in ()).throw(ConnectionError()),
                    allowed)
        self.assertEqual(len(journal), 1)
        finished = advance(CounterGame(), journal, lambda h, o: {'type': 'step'}, allowed)
        self.assertEqual(finished['result']['terminal_reason'], 'completed')
        broken = [dict(finished['journal'][0], observation_sha256='0' * 64)]
        with self.assertRaises(ValueError): replay(CounterGame(), broken, allowed)

    def test_extra_model_output_is_not_echoed_as_scratchpad(self):
        journal = []
        advance(CounterGame(), journal, lambda h, o: {'type': 'step', 'notes': 'hidden notes'}, allowed)
        self.assertEqual([x['action'] for x in journal], [{'type': 'invalid'}] * 2)

if __name__ == '__main__': unittest.main()
