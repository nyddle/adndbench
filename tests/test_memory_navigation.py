from collections import deque
import json
import os
import subprocess
import sys
import unittest

from benchmark.memory_navigation import create_game, LEVELS, ITEMS, SYSTEM_PROMPTS


class MemoryNavigationTest(unittest.TestCase):
    def test_memory_interactions_and_isolation(self):
        for level, expected_count in [('easy', 4), ('medium', 12), ('hard', 32)]:
            for seed in range(20):
                game = create_game('memory', seed, level)
                first = game.observe()
                answer = first['encounter']['request']
                person = first['encounter']['person']
                self.assertTrue(first['encounter']['main'])
                actors = {person}
                for _ in range(expected_count):
                    obs = game.step({'type': 'move', 'direction': 'forward'})
                    self.assertFalse(obs['encounter']['main'])
                    self.assertNotEqual(obs['encounter']['person'], person)
                    actors.add(obs['encounter']['person'])
                    self.assertNotIn('query', obs)
                self.assertEqual(len(actors), expected_count + 1)
                gate = game.step({'type': 'move', 'direction': 'forward'})
                self.assertEqual(gate['query']['person'], person)
                self.assertNotIn('encounter', gate)
                self.assertEqual(gate['query']['choices'], list(ITEMS))
                game.step({'type': 'answer', 'item': answer})
                self.assertTrue(game.done)
                self.assertEqual(game.result()['terminal_reason'], 'completed')
                with self.assertRaises(RuntimeError): game.step({'type': 'move', 'direction': 'forward'})

    def test_wrong_and_invalid_actions(self):
        game = create_game('memory', 1, 'easy')
        answer = game.observe()['encounter']['request']
        for _ in range(game.config['distractors']+1): game.step({'type': 'move', 'direction': 'forward'})
        game.step({'type': 'answer', 'item': next(i for i in ITEMS if i != answer)})
        self.assertEqual(game.result()['terminal_reason'], 'incorrect_answer')
        game = create_game('navigation', 1, 'easy')
        for action in ({}, {'type': 'move', 'direction': []}, {'type': 'move', 'direction': 'up'}, None):
            game.step(action)
        self.assertEqual(game.invalid_actions, 4)

    def test_navigation_graph_oracle_and_partial_observation(self):
        opposite = {'north':'south', 'south':'north', 'east':'west', 'west':'east'}
        for level in LEVELS:
            for seed in range(25):
                game = create_game('navigation', seed, level)
                obs = game.observe()
                self.assertEqual(set(obs), {'scenario','room','exits','goal','turn','max_turns','done','message'})
                self.assertEqual(len(set(game.names.values())), len(game.names))
                for point, exits in game.edges.items():
                    for direction, dest in exits.items():
                        self.assertEqual(game.edges[dest][opposite[direction]], point)
                queue = deque([(game.position, [])]); seen = {game.position}; path = None
                while queue:
                    pos, directions = queue.popleft()
                    if pos == game.target: path = directions; break
                    for direction, dest in game.edges[pos].items():
                        if dest not in seen:
                            seen.add(dest); queue.append((dest, directions+[direction]))
                self.assertIsNotNone(path)
                self.assertEqual(len(path), game.optimal_path_length)
                self.assertGreaterEqual(len(path), game.config['side'])
                self.assertLessEqual(len(path), game.max_turns)
                for direction in path: game.step({'type': 'move', 'direction': direction})
                self.assertTrue(game.result()['completed'])
                self.assertEqual(game.turn, len(path))

    def test_no_seed_or_prior_record_in_observations(self):
        seed = 'SECRET-SEED-a9e10b'
        for vector in SYSTEM_PROMPTS:
            game = create_game(vector, seed, 'easy')
            self.assertNotIn(seed, json.dumps(game.observe(), ensure_ascii=False))
            if vector == 'memory':
                initial = game.observe()['encounter']
                next_obs = game.step({'type': 'move', 'direction': 'forward'})
                self.assertNotIn(initial['person'], json.dumps(next_obs, ensure_ascii=False))
                for _ in range(game.config['distractors']):
                    next_obs = game.step({'type': 'move', 'direction': 'forward'})
                self.assertNotIn('answer', next_obs)
                self.assertNotIn('records', next_obs)
                self.assertNotIn('encounter', next_obs)

    def test_validation_and_reproducibility(self):
        for vector in SYSTEM_PROMPTS:
            for level in LEVELS:
                a, b = create_game(vector, 'dev', level), create_game(vector, 'dev', level)
                self.assertEqual(a.observe(), b.observe())
        for args in [('navigation', None, 'easy'), ('memory', True, 'easy'), ('memory', 1, 'unknown'), ('other', 1, 'easy')]:
            with self.assertRaises(ValueError): create_game(*args)
        code = "import json; from benchmark.memory_navigation import create_game; print(json.dumps(create_game('navigation','test','hard').observe(),sort_keys=True))"
        results = [subprocess.check_output([sys.executable, '-c', code], env={**os.environ,'PYTHONHASHSEED': seed}) for seed in ('1', '22')]
        self.assertEqual(results[0], results[1])

if __name__ == '__main__': unittest.main()
