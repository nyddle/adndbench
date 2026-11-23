import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import paired_radical_adventure as wrap


class IntegratedRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        engine=wrap.engine
        self.patches=[patch.object(engine,'BASE',Path(self.tmp.name)),
                      patch.object(engine,'fingerprint',wrap.fingerprint),
                      patch.object(engine,'create_game',wrap.create_game),
                      patch.object(engine,'rule',wrap.rule),patch.object(engine,'actions',wrap.actions),
                      patch.object(engine,'canonical_action',wrap.canonical),
                      patch.object(engine,'status',wrap.status),
                      patch.object(engine,'cli_version',return_value='test-cli')]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        self.config={'memory':'medium','navigation':'easy','quests':'medium',
                     'combat':'off','party':False,'max_turns':30}

    def test_codes_preserve_outcomes_and_never_allow_a_free_retry(self):
        p={'adapter':wrap.ADAPTER,'game_config':self.config}
        for code in ('not-valid-code','sun-tree-moon-star'):
            game=wrap.create_game(p,'dev-public-seed')
            game.briefed=True;game.position=game.goal_room
            goal=next(t for t in game.quest.plan['tasks'] if t['id']==game.quest.plan['goal'])
            game.quest.completed=set(goal['requires']);game.quest.inventory=set(goal['consumes'])
            expected='-'.join(game.code)
            submitted=expected if code=='sun-tree-moon-star' else code
            action=wrap.canonical({'type':'unlock','code':submitted},wrap.actions(p,game.observe()))
            game.step(action)
            if submitted==expected:
                self.assertTrue(game.unlocked)
            else:
                self.assertEqual(game.terminal_reason,'incorrect_code')
                self.assertTrue(game.done)

    def test_private_plan_pairing_and_budget(self):
        with contextlib.redirect_stdout(io.StringIO()):
            wrap.init('test',self.config,1,1,2,4,10000,2)
        d,p,state=wrap.engine.load('test')
        self.assertEqual(os.stat(d/'plan.json').st_mode&0o077,0)
        self.assertNotEqual(p['seeds']['dev'][0],p['seeds']['holdout'][0])
        self.assertEqual(p['models'],list(wrap.engine.MODELS))
        self.assertEqual(p['reasoning_effort'],'low')
        def call(text,model,timeout):
            latest=json.loads((d/'state.json').read_text())
            self.assertIn('inflight',{e['status'] for e in latest['episodes'].values()})
            self.assertNotIn(p['seeds']['dev'][0],text)
            return {'action':{'type':'talk'},'usage':{'input_tokens':10,'output_tokens':1}}
        with patch.object(wrap.engine,'call',side_effect=call) as mock,contextlib.redirect_stdout(io.StringIO()):
            wrap.engine.run('test','dev')
        self.assertEqual([c.args[1] for c in mock.call_args_list],list(wrap.engine.MODELS)*2)
        out=io.StringIO()
        with contextlib.redirect_stdout(out):wrap.engine.status('test')
        report=json.loads(out.getvalue())
        self.assertEqual(report['groups'][0]['paired_outcomes']['incomplete'],1)
        self.assertEqual(report['game_config'],self.config)
        self.assertNotIn(p['seeds']['dev'][0],out.getvalue())
        with self.assertRaises(ValueError):wrap.engine.seal('test')

    def test_window_must_retain_starting_clue(self):
        with self.assertRaises(ValueError):wrap.init('bad',self.config,1,1,20,40,10000,5)

    def test_prompt_lists_only_public_actions_not_all_codes(self):
        p={'adapter':wrap.ADAPTER,'game_config':self.config}
        game=wrap.create_game(p,'public-seed');obs=game.observe();act=wrap.actions(p,obs)
        self.assertEqual(len([a for a in act if a['type']=='unlock']),1)
        self.assertFalse([a for a in act if a['type']=='recruit'])
        self.assertNotIn('public-seed',json.dumps(obs,ensure_ascii=False))
        self.assertNotIn('public-seed',json.dumps(act,ensure_ascii=False))

if __name__=='__main__':unittest.main()
