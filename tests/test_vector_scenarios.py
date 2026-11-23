import unittest
from benchmark.vector_harness import advance, replay, canonical_action
from benchmark.vector_scenarios import create_game, allowed_actions, SCENARIOS, LEVELS
from benchmark.quest_chains import oracle
from benchmark.adventure_vectors import oracle as adventure_oracle


class ScenarioIntegrationTests(unittest.TestCase):
    def test_factory_and_observation_do_not_expose_seed(self):
        for axis in SCENARIOS:
            for level in LEVELS:
                with self.subTest(axis=axis, level=level):
                    game = create_game(axis, 'SECRET_SEED_TEST_46512', level)
                    self.assertNotIn('SECRET_SEED_TEST_46512', repr(game.observe()))
                    self.assertTrue(allowed_actions(axis, game.observe()))

    def test_quest_oracle_runs_through_common_harness_and_replays(self):
        game = create_game('quests', 'test-integration', 'hard')
        actions = iter(oracle(game.plan))
        journal = []
        result = advance(game, journal, lambda h, o: next(actions), lambda o: allowed_actions('quests', o))
        self.assertEqual(result['result']['terminal_reason'], 'completed')
        self.assertEqual(result['result']['extra_turns'], 0)
        replayed = create_game('quests', 'test-integration', 'hard')
        obs, _ = replay(replayed, journal, lambda o: allowed_actions('quests', o))
        self.assertEqual(obs['terminal_reason'], 'completed')

    def test_combined_adventure_replays_through_common_harness(self):
        game = create_game('adventure-quests', 'test-integration', 'hard')
        actions = iter(adventure_oracle(game))
        journal = []
        result = advance(game, journal, lambda h, o: next(actions),
                         lambda o: allowed_actions('adventure-quests', o))
        self.assertEqual(result['result']['terminal_reason'], 'completed')
        resumed = create_game('adventure-quests', 'test-integration', 'hard')
        self.assertTrue(replay(resumed, journal,
                               lambda o: allowed_actions('adventure-quests', o))[0]['done'])

    def test_wrong_unlock_is_a_consumed_attempt_through_adapter(self):
        game = create_game('adventure-memory', 'wrong-code-test', 'easy')
        actions = adventure_oracle(game)
        for action in actions:
            if action['type'] == 'unlock': break
            game.step(action)
        invalid_code = {'type':'unlock', 'code':'not-a-rune'}
        game.step(canonical_action(invalid_code, allowed_actions('adventure-memory', game.observe())))
        self.assertEqual(game.result()['terminal_reason'], 'incorrect_code')

    def test_party_invalid_move_reports_failure(self):
        game = create_game('party', 'test-move', 'easy')
        self.assertNotIn('south', game.observe()['exits'])
        after = game.step({'type':'move', 'direction':'south'})
        self.assertEqual(after['room'], 'Убежище')
        self.assertIn('выхода нет', after['message'])
        self.assertEqual(game.result()['invalid_actions'], 1)

    def test_memory_observation_history_produces_correct_answer(self):
        game = create_game('memory', 'test-integration', 'easy')
        def decide(history, obs):
            if obs['location'] != 'Ворота': return {'type':'move','direction':'forward'}
            return {'type':'answer','item':history[0]['observation']['encounter']['request']}
        result = advance(game, [], decide, lambda o: allowed_actions('memory', o))
        self.assertEqual(result['result']['terminal_reason'], 'completed')

    def test_party_scenario_is_playable_via_public_actions(self):
        game = create_game('tactics', 'test-integration', 'easy')
        route = iter(['north', 'north', 'north'])
        def decide(history, obs):
            battle = obs['battle']
            if battle:
                return {'type':'strike', 'actor':'hero', 'target':battle['enemies'][0]['id']}
            if obs['inventory']:
                return {'type':'move','direction':'south'}
            if obs['room'] == 'Логово': return {'type':'search'}
            return {'type':'move','direction':next(route)}
        journal = []
        result = advance(game, journal, decide, lambda o: allowed_actions('tactics', o))
        self.assertEqual(result['result']['terminal_reason'], 'completed')
        self.assertEqual(replay(create_game('tactics','test-integration','easy'), journal,
                                lambda o: allowed_actions('tactics', o))[0]['done'], True)

if __name__ == '__main__': unittest.main()
