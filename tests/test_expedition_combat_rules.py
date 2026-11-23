"""Verify tactical timing against the integrated game, not just the module."""
import unittest
from benchmark.expedition import Game


class CombatTimingTests(unittest.TestCase):
    def test_early_wizard_visit_gives_ward_at_source_without_softlock(self):
        for difficulty in ('easy', 'medium'):
            with self.subTest(difficulty=difficulty):
                game = Game(3, quest_difficulty=difficulty)
                game.position = game.world['sites']['wizard']
                obs = game.step({'type': 'talk'})
                self.assertIn('рунический оберег', obs['inventory'])
                self.assertIn('Маг', obs['message'])
                game.position = game.world['sites']['elder']
                obs = game.step({'type': 'talk'})
                self.assertEqual(obs['inventory'].count('рунический оберег'), 1)
                self.assertIn('Засчитан ранее полученный оберег', obs['message'])
                self.assertIn('main_ward', game.quest_state['completed_objectives'])

    def test_invalid_action_in_combat_triggers_the_telegraphed_response(self):
        game = Game(3, combat_difficulty='hard')
        # Place the evaluator at the generated boss encounter; all following
        # state changes are made through public actions.
        game.position = game.world['sites']['dragon']
        self.assertEqual(game.observe()['enemy']['intent']['id'], 'breath')
        obs = game.step({'type': 'not-an-action'})
        self.assertEqual(obs['hp'], 10)
        self.assertEqual(obs['enemy']['intent']['id'], 'claws')
        self.assertEqual(game.result()['invalid_actions'], 1)
        obs = game.step({'type': 'not-an-action'})
        self.assertEqual(obs['hp'], 6)
        self.assertEqual(obs['enemy']['intent']['id'], 'breath')
        self.assertEqual(game.result()['invalid_actions'], 2)

    def test_combat_difficulty_changes_intent_at_fixed_encounter_count(self):
        easy = Game(3, combat_difficulty='easy', enemy_count=2)
        hard = Game(3, combat_difficulty='hard', enemy_count=2)
        self.assertEqual(set(easy.encounters), set(hard.encounters))
        easy.position = easy.world['sites']['dragon']
        hard.position = hard.world['sites']['dragon']
        easy_intent = easy.observe()['enemy']['intent']
        hard_intent = hard.observe()['enemy']['intent']
        self.assertLess(easy_intent['damage'], hard_intent['damage'])
        self.assertEqual(easy.result()['additional_encounters_generated'],
                         hard.result()['additional_encounters_generated'])


if __name__ == '__main__':
    unittest.main()
