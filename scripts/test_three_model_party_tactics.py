import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import three_model_party_tactics as pilot
from benchmark.party_combat import Battle, shortest_victory


class PartyTacticsPilotTests(unittest.TestCase):
    def test_role_choice_is_distinct_from_execution(self):
        results={}
        for role in pilot.probe.ROLES_AVAILABLE:
            game=pilot.probe.Game('case','party','fixed')
            game.step({'type':'recruit','candidate':role})
            results[role]=game.result()['terminal_reason']
        self.assertEqual(results,{'warden':'wrong_choice','medic':'wrong_choice','mage':'completed'})

    def test_tactical_oracle_and_invalid_consumes_round(self):
        for level in ('one','two','three'):
            game=pilot.probe.Game('case','tactics',level)
            path=shortest_victory(game.battle)
            self.assertEqual(path['status'],'solved')
            for action in path['actions']:
                self.assertIn(action,pilot.probe.allowed_actions('tactics',game.observe()))
                game.step(action)
            self.assertEqual(game.result()['terminal_reason'],'completed')
        game=pilot.probe.Game('case','tactics','three')
        game.step({'type':'invalid'})
        self.assertEqual(game.turn,1)
        self.assertEqual(game.invalid_actions,1)
        self.assertLess(game.battle.party.members['hero']['hp'],12)

    def test_runner_replays_same_case_and_reports_three_models(self):
        with tempfile.TemporaryDirectory() as td:
            pilot.BASE=Path(td)
            pilot.configure()
            with patch.object(pilot.engine,'cli_version',return_value='test'), \
                 patch.object(pilot.engine,'call',return_value={'action':{'type':'recruit','candidate':'mage'},'usage':{'input_tokens':10}}), \
                 contextlib.redirect_stdout(io.StringIO()):
                pilot.init('demo','party','fixed',45,100000)
                pilot.engine.run('demo','dev')
                _,p,st=pilot.engine.load('demo')
                self.assertEqual(p['seeds']['holdout'],[])
                self.assertEqual(len(st['receipts']['dev']),3)
                for model in pilot.MODELS:
                    game,_=pilot.engine.reconstruct(p,p['seeds']['dev'][0],st['episodes'][pilot.engine.key_for('dev',1,model)])
                    self.assertEqual(game.terminal_reason,'completed')


if __name__=='__main__': unittest.main()
