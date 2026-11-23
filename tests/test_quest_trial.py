import json
import os
import subprocess
import sys
import unittest
from benchmark.quest_trial import LEVELS, PARAMETERS, QuestTrial, generate_plan, oracle, source_fingerprint


class QuestTrialTests(unittest.TestCase):
    def test_seed_version_and_observations_are_private(self):
        secret='not-for-public-9bcdf38'
        for level in LEVELS:
            game=QuestTrial(secret,level)
            self.assertNotIn(secret,json.dumps(game.observe(),ensure_ascii=False))
            self.assertEqual(game.observe(),QuestTrial(secret,level).observe())
            self.assertEqual(len(game.plan['tasks']),PARAMETERS[level][0]*PARAMETERS[level][1]+PARAMETERS[level][2]+1)
        self.assertEqual(len(source_fingerprint()),64)
        for invalid in (True,[],None):
            with self.assertRaises(ValueError):QuestTrial(invalid)
        with self.assertRaises(ValueError):QuestTrial('s','unknown')

    def test_bfs_solution_and_replay_across_dev_worlds(self):
        for level in LEVELS:
            for seed in range(25):
                game=QuestTrial(seed,level)
                verdict=oracle(game)
                self.assertEqual(verdict['status'],'solved')
                self.assertEqual(len(verdict['actions']),game.optimal_turns)
                clone=QuestTrial(seed,level)
                for action in verdict['actions']:
                    self.assertEqual(game.step(action),clone.step(action))
                self.assertTrue(game.done)
                self.assertEqual(game.terminal_reason,'completed')
                self.assertEqual(game.result()['extra_turns'],0)
                self.assertEqual(game.result(),clone.result())
                with self.assertRaises(RuntimeError):game.step({'type':'perform','target':'bad'})

    def test_irreversible_trade_is_explicit_and_makes_goal_impossible(self):
        game=QuestTrial('dev-trade','hard')
        decoy=next(x for x in game.observe()['tasks'] if x['description']=='Обменять на побочную награду')
        initial_solution=oracle(game)['actions']
        # Follow the shortest path only until the decoy's preconditions are met.
        for action in initial_solution:
            if set(decoy['requires'])<=game.completed and set(decoy['consumes'])<=game.inventory:break
            game.step(action)
        else:self.fail('decoy never became available')
        self.assertFalse(game.done)
        old=set(game.inventory)
        game.step({'type':'perform','target':decoy['id']})
        self.assertTrue(set(decoy['consumes'])<=old)
        self.assertTrue(set(decoy['produces'])<=game.inventory)
        self.assertTrue(set(decoy['consumes']).isdisjoint(game.inventory))
        self.assertEqual(oracle(game)['status'],'unsolvable')

    def test_invalid_actions_advance_time_and_strict_schema(self):
        game=QuestTrial('dev','medium',max_turns=2)
        initial=game.observe()['tasks'][0]['id']
        game.step({'type':'perform','target':initial,'note':'scratchpad'})
        game.step({'type':'perform','target':'unknown'})
        self.assertEqual(game.invalid_actions,2)
        self.assertEqual(game.terminal_reason,'turn_limit')

    def test_oracle_respects_remaining_turn_budget(self):
        game=QuestTrial('dev','medium',max_turns=10)
        self.assertEqual(oracle(game)['status'],'unsolvable')
        game=QuestTrial('dev','medium',max_turns=11)
        self.assertEqual(oracle(game)['status'],'solved')
        game.step({'type':'invalid'})
        self.assertEqual(oracle(game)['status'],'unsolvable')

    def test_unknown_not_unsolvable_when_search_capped(self):
        self.assertEqual(oracle(QuestTrial('dev','hard'),max_states=1)['status'],'unknown')

    def test_hash_seed_does_not_change_world(self):
        code='import json; from benchmark.quest_trial import QuestTrial; print(json.dumps(QuestTrial("dev", "extreme").observe(), ensure_ascii=False, sort_keys=True))'
        outputs=[subprocess.check_output([sys.executable,'-c',code],env={**os.environ,'PYTHONHASHSEED':s}) for s in ('5','561')]
        self.assertEqual(outputs[0],outputs[1])

if __name__=='__main__':unittest.main()
