import json
import os
import subprocess
import sys
import unittest

from benchmark.memory_updates import (create_game, final_request, LEVELS, MAX_CHOICES,
                                      PARAMS, ITEMS_DISTINCT, ITEMS_SIMILAR)


def play_to_gate(game):
    while not game.done and game.observe().get('encounter') is not None:
        game.step({'type': 'move', 'direction': 'forward'})
    return game.observe()


class MemoryUpdatesTest(unittest.TestCase):
    def test_protocol_updates_and_lures(self):
        for level in LEVELS:
            params = PARAMS[level]
            for seed in range(20):
                game = create_game(seed, level)
                encounters = []
                while True:
                    obs = game.observe()
                    if obs.get('encounter') is None:
                        break
                    encounters.append(obs['encounter'])
                    game.step({'type': 'move', 'direction': 'forward'})
                self.assertEqual(len(encounters), params['persons'] + params['updates'])
                self.assertTrue(encounters[0]['main'])
                self.assertFalse(encounters[0]['update'])
                target = encounters[0]['person']
                self.assertEqual(sum(e['person'] == target and e['update'] for e in encounters),
                                 game.target_updates)
                self.assertGreaterEqual(game.target_updates, 1)
                # The last encounter never belongs to the target person.
                self.assertNotEqual(encounters[-1]['person'], target)
                # Ground truth equals sequential application of updates.
                self.assertEqual(game.answer, final_request(game.records, target))
                # The first-mentioned value can never cycle back into the answer.
                self.assertNotEqual(encounters[0]['request'], game.answer)
                # Choices contain the answer, at least one past value, and are unique.
                self.assertIn(game.answer, game.choices)
                self.assertEqual(len(game.choices), len(set(game.choices)))
                self.assertLessEqual(len(game.choices), MAX_CHOICES)
                earlier = [e['request'] for e in encounters
                           if e['person'] == target and e['request'] != game.answer]
                self.assertTrue(earlier)
                self.assertTrue(any(item in game.choices for item in earlier))
                gate = game.observe()
                self.assertEqual(gate['query']['person'], target)
                self.assertEqual(gate['query']['choices'], game.choices)

    def test_answer_outcomes_and_invalid_actions(self):
        game = create_game(1, 'easy')
        play_to_gate(game)
        game.step({'type': 'answer', 'item': game.answer})
        self.assertTrue(game.done)
        self.assertEqual(game.result()['terminal_reason'], 'completed')
        with self.assertRaises(RuntimeError):
            game.step({'type': 'move', 'direction': 'forward'})
        game = create_game(1, 'easy')
        play_to_gate(game)
        wrong = next(item for item in game.choices if item != game.answer)
        game.step({'type': 'answer', 'item': wrong})
        self.assertEqual(game.result()['terminal_reason'], 'incorrect_answer')
        game = create_game(2, 'easy')
        for action in ({}, {'type': 'move', 'direction': 'north'}, None,
                       {'type': 'answer', 'item': 'несуществующий предмет'}):
            game.step(action)
        self.assertEqual(game.invalid_actions, 4)

    def test_similar_pool_on_hard(self):
        game = create_game('dev', 'hard')
        self.assertTrue(all(item in ITEMS_SIMILAR for item in game.choices))
        game = create_game('dev', 'easy')
        self.assertTrue(all(item in ITEMS_DISTINCT for item in game.choices))

    def test_no_seed_or_records_in_observations(self):
        seed = 'SECRET-SEED-b7f20c'
        game = create_game(seed, 'medium')
        while True:
            obs = game.observe()
            text = json.dumps(obs, ensure_ascii=False)
            self.assertNotIn(seed, text)
            self.assertNotIn('records', text)
            self.assertNotIn('answer', text)
            if obs.get('encounter') is None:
                break
            game.step({'type': 'move', 'direction': 'forward'})

    def test_scratchpad_notes(self):
        game = create_game(1, 'easy')
        self.assertEqual(game.observe()['notes'], '')
        obs = game.step({'type': 'move', 'direction': 'forward', 'notes': 'главный: ключ'})
        self.assertEqual(obs['notes'], 'главный: ключ')
        # Notes persist across actions that do not carry them.
        obs = game.step({'type': 'move', 'direction': 'forward'})
        self.assertEqual(obs['notes'], 'главный: ключ')
        # Invalid notes invalidate the whole action without advancing.
        before = game.index
        for bad in (123, 'x' * 501):
            obs = game.step({'type': 'move', 'direction': 'forward', 'notes': bad})
            self.assertEqual(game.index, before)
            self.assertEqual(obs['notes'], 'главный: ключ')
        self.assertEqual(game.invalid_actions, 2)
        # Notes ride along the gate answer too.
        while game.observe().get('encounter') is not None:
            game.step({'type': 'move', 'direction': 'forward'})
        game.step({'type': 'answer', 'item': game.answer, 'notes': 'финиш'})
        self.assertEqual(game.result()['terminal_reason'], 'completed')

    def test_validation_and_reproducibility(self):
        for level in LEVELS:
            a, b = create_game('dev', level), create_game('dev', level)
            self.assertEqual(a.observe(), b.observe())
            self.assertEqual(a.choices, b.choices)
            self.assertEqual(a.records, b.records)
        for args in [(None, 'easy'), (True, 'easy'), (1, 'unknown')]:
            with self.assertRaises(ValueError):
                create_game(*args)
        code = ("import json; from benchmark.memory_updates import create_game; "
                "g = create_game('test', 'hard'); "
                "print(json.dumps([g.observe(), g.choices], sort_keys=True, ensure_ascii=False))")
        results = [subprocess.check_output([sys.executable, '-c', code],
                                           env={**os.environ, 'PYTHONHASHSEED': seed})
                   for seed in ('1', '22')]
        self.assertEqual(results[0], results[1])


if __name__ == '__main__':
    unittest.main()
