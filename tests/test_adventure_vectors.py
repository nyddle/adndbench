from collections import deque
import unittest
from benchmark.adventure_vectors import Game, LEVELS, RUNES, oracle


class AdventureVectorsTests(unittest.TestCase):
    def test_difficulty_axis_isolation_and_nesting(self):
        for seed in range(30):
            games = [Game(seed, navigation=x) for x in LEVELS]
            for g in games[1:]:
                self.assertEqual(g.names, games[0].names)
                self.assertEqual(g.tasks, games[0].tasks)
                self.assertEqual(g.code, games[0].code)
                self.assertEqual(g.lock, games[0].lock)
            for room in games[0].edges:
                self.assertGreaterEqual(set(games[0].edges[room]), set(games[1].edges[room]))
                self.assertGreaterEqual(set(games[1].edges[room]), set(games[2].edges[room]))
                for d, dest in games[2].edges[room].items(): self.assertEqual(games[0].edges[room][d], dest)
            memory = [Game(seed, memory=x) for x in LEVELS]
            self.assertEqual([len(g.code) for g in memory], [1,2,3])
            self.assertEqual(memory[2].code[:1], memory[0].code)
            self.assertEqual(memory[2].code[:2], memory[1].code)
            self.assertTrue(all(g.edges == memory[0].edges and g.tasks == memory[0].tasks for g in memory))
            quests = [Game(seed, quests=x) for x in LEVELS]
            self.assertEqual([len(g.tasks) for g in quests], [1,3,5])
            self.assertEqual(quests[0].tasks, quests[2].tasks[:1])
            self.assertEqual(quests[1].tasks, quests[2].tasks[:3])
            self.assertTrue(all(g.edges == quests[0].edges and g.code == quests[0].code for g in quests))

    def test_oracle_replay_all_variants(self):
        for seed in range(25):
            for memory in LEVELS:
                for nav in LEVELS:
                    for quest in LEVELS:
                        game = Game(seed, memory=memory, navigation=nav, quests=quest)
                        actions = oracle(game)
                        for action in actions: game.step(action)
                        self.assertTrue(game.done)
                        self.assertEqual(game.terminal_reason, 'completed')
                        self.assertEqual(game.invalid_actions, 0)
                        replay = Game(seed, memory=memory, navigation=nav, quests=quest)
                        for action in actions: replay.step(action)
                        self.assertEqual(game.result(), replay.result())
                        self.assertEqual(game.observe(), replay.observe())

    def test_one_shot_clue_and_wrong_code(self):
        game = Game('unique-private-test', memory='medium')
        start = game.observe()
        self.assertNotIn('unique-private-test', repr(start))
        self.assertNotIn('runes', start['notice'])
        clue = game.step({'type':'talk'})['notice']['runes']
        self.assertEqual(len(clue),2)
        self.assertTrue(all(x in RUNES for x in clue))
        self.assertNotIn('runes', game.step({'type':'talk'})['notice'])
        for action in oracle(Game('unique-private-test', memory='medium'))[1:]:
            if action['type'] == 'unlock':
                action = {'type':'unlock','code':'invalid'}
                game.step(action)
                break
            game.step(action)
        self.assertEqual(game.terminal_reason, 'incorrect_code')
        self.assertNotIn('runes', game.observe()['notice'])

    def test_errors_and_prerequisites(self):
        game = Game(2, quests='hard')
        game.step({'type':'talk'})
        g0 = len(game.completed_tasks)
        game.step({'type':'interact','target':'Q5'})
        self.assertEqual(len(game.completed_tasks),g0)
        self.assertEqual(game.invalid_actions,1)
        game.step({'type':'move','direction':[]})
        self.assertEqual(game.invalid_actions,2)
        game.step({'type':'unlock','code':'sun'})
        self.assertEqual(game.invalid_actions,3)
        self.assertFalse(game.done)
        with self.assertRaises(ValueError): Game(True)
        with self.assertRaises(ValueError): Game(1,memory='bad')

if __name__ == '__main__': unittest.main()
