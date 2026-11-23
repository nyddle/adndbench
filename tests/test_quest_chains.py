"""Exercise quest-chain action semantics and independently check its oracle."""
import json
import os
import subprocess
import sys
import unittest

from benchmark.quest_chains import LEVELS, QuestChain, generate_plan, oracle


class QuestChainTests(unittest.TestCase):
    def test_graph_and_level_are_a_controlled_intervention(self):
        for seed in range(40):
            plans = {level: generate_plan(seed, level) for level in LEVELS}
            base = plans['long']
            for level, remaining in LEVELS.items():
                plan = plans[level]
                self.assertEqual(plan['tasks'], base['tasks'])
                self.assertEqual(plan['goal'], base['goal'])
                self.assertEqual(len(plan['tasks']), 12)
                self.assertEqual(len({x['id'] for x in plan['tasks']}), 12)
                self.assertEqual(len({(x['type'], x['target']) for x in plan['tasks']}), 12)
                self.assertEqual(len(plan['initial_done']), 7 - remaining)
                by_id = {x['id']: x for x in plan['tasks']}
                closure = set()
                todo = [plan['goal']]
                while todo:
                    task_id = todo.pop()
                    if task_id not in closure:
                        closure.add(task_id)
                        todo.extend(by_id[task_id]['requires'])
                self.assertEqual(len(closure - set(plan['initial_done'])), remaining + 3)
                self.assertEqual(len(oracle(plan)), remaining + 3)
                episode = QuestChain(seed, level)
                public = episode.observe()
                self.assertNotIn('seed', json.dumps(public, ensure_ascii=False))
                for step in oracle(plan):
                    obs = episode.step(step)
                self.assertEqual(obs['terminal_reason'], 'completed')
                self.assertEqual(episode.result()['extra_turns'], 0)
                self.assertEqual(episode.result()['invalid_actions'], 0)
                with self.assertRaises(ValueError): episode.step({'type': 'talk', 'target': 'none'})

    def test_locked_repeat_and_invalid_consume_turns_and_limit(self):
        episode = QuestChain('test', 'long', max_turns=4)
        tasks = episode.observe()['tasks']
        locked = next(t for t in tasks if t['requires'])
        episode.step({'type': locked['type'], 'target': locked['target']})
        self.assertEqual(episode.result()['invalid_actions'], 1)
        available = next(t for t in tasks if not t['requires'])
        move = {'type': available['type'], 'target': available['target']}
        episode.step(move)
        episode.step(move)
        episode.step({'type': 'talk', 'target': 'other', 'extra': 1})
        result = episode.result()
        self.assertEqual(result['invalid_actions'], 3)
        self.assertEqual(result['turns'], 4)
        self.assertEqual(result['terminal_reason'], 'turn_limit')
        self.assertIsNone(result['extra_turns'])

    def test_observation_is_detached_and_replay_is_deterministic(self):
        first = QuestChain('same', 'medium')
        second = QuestChain('same', 'medium')
        obs = first.observe()
        obs['tasks'].clear()
        self.assertEqual(len(first.observe()['tasks']), 12)
        for action in oracle(first.plan):
            self.assertEqual(first.step(action), second.step(action))
        self.assertEqual(first.result(), second.result())

    def test_input_validation(self):
        for seed in (None, True, [], {}):
            with self.assertRaises(ValueError): QuestChain(seed, 'short')
        with self.assertRaises(ValueError): QuestChain(0, 'bad')
        for turns in (False, 0, -1, 1.2):
            with self.assertRaises(ValueError): QuestChain(0, 'short', turns)

    def test_hashseed_does_not_change_generated_world(self):
        code = ('import json; from benchmark.quest_chains import QuestChain; '
                'print(json.dumps(QuestChain("dev", "medium").observe(), ensure_ascii=False, sort_keys=True))')
        outputs = [subprocess.check_output([sys.executable, '-c', code], env={**os.environ, 'PYTHONHASHSEED': h})
                   for h in ('1', '19')]
        self.assertEqual(outputs[0], outputs[1])


if __name__ == '__main__':
    unittest.main()
