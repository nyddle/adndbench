import unittest

from benchmark.radical_adventure import Game, shortest_directions
from benchmark.radical_efficiency_score import score, VERSION
from benchmark.quest_trial import _legal


def winning_actions():
    game = Game('efficiency-test', memory='medium', navigation='easy',
                quests='medium', combat='off', party=False, max_turns=100)
    actions = []
    def do(action):
        game.step(action)
        actions.append(action)
    def travel(target):
        for direction in shortest_directions(game.edges, game.position, target):
            do({'type':'move', 'direction':direction})
    do({'type':'talk'})
    while not game.done:
        legal = [t for t in game.quest.plan['tasks']
                 if t['description'] != 'Обменять на побочную награду'
                 and _legal(t, frozenset(game.quest.completed), frozenset(game.quest.inventory))]
        task = legal[0]
        travel(game.task_rooms[task['id']])
        if task['id'] == game.quest.plan['goal']:
            do({'type':'unlock', 'code':'-'.join(game.code)})
        do({'type':'perform', 'target':task['id']})
    return game, actions


class EfficiencyScoreTests(unittest.TestCase):
    def test_faster_win_scores_higher_even_with_identical_progress(self):
        fast, actions = winning_actions()
        slow = Game('efficiency-test', memory='medium', navigation='easy',
                    quests='medium', combat='off', party=False, max_turns=100)
        slower_actions = [actions[0], {'type':'invalid'}, *actions[1:]]
        for action in slower_actions:
            slow.step(action)
        a = score(fast, actions, episode_status='completed')
        b = score(slow, slower_actions, episode_status='completed')
        self.assertEqual(a['version'], VERSION)
        self.assertEqual(a['components']['progress']['legacy_score'], 100)
        self.assertEqual(b['components']['progress']['legacy_score'], 100)
        self.assertEqual(a['components']['progress']['earned'], 85)
        self.assertGreater(a['score'], b['score'])
        self.assertAlmostEqual(a['score'] - b['score'], .15)
        self.assertTrue(a['win'])

    def test_game_loss_gets_progress_but_no_speed_bonus(self):
        game = Game('efficiency-lost', max_turns=1)
        actions = [{'type':'talk'}]
        game.step(actions[0])
        out = score(game, actions, episode_status='completed')
        self.assertEqual(out['terminal_reason'], 'turn_limit')
        self.assertFalse(out['win'])
        self.assertEqual(out['components']['efficiency']['earned'], 0)
        self.assertEqual(out['components']['efficiency']['status'], 'not_eligible')

    def test_technical_and_inflight_never_award_a_score(self):
        game, actions = winning_actions()
        for status in ('technical_error', 'inflight', 'action_limit'):
            out = score(game, actions, episode_status=status)
            self.assertIsNone(out['score'])
            self.assertIsNone(out['win'])
            self.assertIsNone(out['components']['progress']['earned'])
            self.assertEqual(out['components']['efficiency']['status'], 'not_scored')

    def test_replay_validation_and_inconsistent_completed_status(self):
        game = Game('efficiency-unfinished')
        self.assertIsNone(score(game, [], episode_status='ready')['score'])
        with self.assertRaises(ValueError):
            score(game, [], episode_status='completed')
        game.step({'type':'talk'})
        with self.assertRaises(ValueError):
            score(game, [], episode_status='ready')
        with self.assertRaises(ValueError):
            score(game, [{'type':'talk'}], episode_status='')


if __name__ == '__main__':
    unittest.main()
