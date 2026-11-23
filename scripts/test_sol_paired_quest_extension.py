import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import sol_paired_quest_extension as wrap
from benchmark.radical_score import required_task_ids
from benchmark.quest_trial import _legal


class SolExtensionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.parent=Path(self.tmp.name)/'reference';self.dest=Path(self.tmp.name)/'sol';self.e=wrap.engine
        self.patches=[patch.object(wrap,'PARENT_BASE',self.parent),patch.object(wrap,'BASE',self.dest),
                      patch.multiple(self.e,BASE=self.e.BASE,MODELS=self.e.MODELS,
                                     fingerprint=self.e.fingerprint,status=self.e.status),
                      patch.object(self.e,'cli_version',return_value='test-cli')]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        self.e.BASE=self.parent;self.e.MODELS=wrap.SOURCE_MODELS;self.e.fingerprint=wrap._original_fingerprint
        with contextlib.redirect_stdout(io.StringIO()):
            self.e.init('ref','quest_trial','quests','hard',1,1,24,55,100000,24)

    def complete_reference(self):
        d,p,st=self.e.load('ref')
        for world,seed,model in self.e.specs(p,'dev'):
            game=self.e.create_game(p,seed);required=required_task_ids(game.plan);journal=[]
            while not game.done:
                obs=game.observe();task=next(t for t in game.plan['tasks'] if t['id'] in required and _legal(t,frozenset(game.completed),frozenset(game.inventory)))
                action={'type':'perform','target':task['id']}
                journal.append({'observation_sha256':self.e.digest(obs),'action':action});game.step(action)
            self.assertEqual(game.terminal_reason,'completed')
            st['episodes'][self.e.key_for('dev',world,model)]={'status':'completed','turns':journal,'result':game.result()}
        self.e.write(d/'state.json',st)
        return p

    def test_reference_verified_sol_uses_same_dev_not_holdout(self):
        reference=self.complete_reference()
        with contextlib.redirect_stdout(io.StringIO()):wrap.init('sol','ref')
        d,p,_=self.e.load('sol')
        self.assertEqual(p['seeds']['dev'],reference['seeds']['dev'])
        self.assertEqual(p['seeds']['holdout'],[])
        self.assertNotIn(reference['seeds']['holdout'][0],json.dumps(p,ensure_ascii=False))
        for field in ('system_prompt','context_turns','level','axis','reasoning_effort','max_actions_per_game','call_timeout','max_calls_per_split','max_input_tokens_per_split'):
            self.assertEqual(p[field],reference[field])
        self.assertEqual(p['models'],['gpt-6.2-sol'])
        def call(text,model,timeout):
            self.assertNotIn(p['seeds']['dev'][0],text)
            obs=json.loads(text.split('\n',1)[1])['current_observation']
            plan={'tasks':obs['tasks'],'goal':obs['goal'],'initial_inventory':[]}
            required=required_task_ids(plan);completed=frozenset(obs['completed']);inventory=frozenset(obs['inventory'])
            target=next(t['id'] for t in obs['tasks'] if t['id'] in required and _legal(t,completed,inventory))
            return {'action':{'type':'perform','target':target},'usage':{'input_tokens':1}}
        with patch.object(self.e,'call',side_effect=call) as mocked,contextlib.redirect_stdout(io.StringIO()):
            self.e.run('sol','dev')
        self.assertEqual(mocked.call_count,19)
        out=io.StringIO()
        with contextlib.redirect_stdout(out):wrap.status('sol')
        result=json.loads(out.getvalue()); self.assertEqual(result['worlds'][0]['sol']['result']['terminal_reason'],'completed')
        self.assertNotIn(p['seeds']['dev'][0],out.getvalue())
        self.assertEqual({x['model'] for x in result['worlds'][0]['reference']},set(wrap.SOURCE_MODELS))
        # Source's paired plan and finished records have not changed.
        self.e.BASE=self.parent;self.e.MODELS=wrap.SOURCE_MODELS;self.e.fingerprint=wrap._original_fingerprint
        _,_,old=self.e.load('ref');self.assertEqual({x['status'] for x in old['episodes'].values()},{'completed'})

    def test_reference_incomplete_is_rejected(self):
        with self.assertRaises(ValueError):wrap.init('sol','ref')
        self.assertFalse((self.dest/'sol'/'plan.json').exists())

    def test_uncertain_sol_call_is_not_retried(self):
        self.complete_reference()
        with contextlib.redirect_stdout(io.StringIO()):wrap.init('sol','ref')
        with patch.object(self.e,'call',return_value={'error':'timeout'}) as mocked,contextlib.redirect_stdout(io.StringIO()):
            self.e.run('sol','dev')
        self.assertEqual(mocked.call_count,1)
        with self.assertRaises(ValueError):self.e.run('sol','dev')
        out=io.StringIO()
        with contextlib.redirect_stdout(out):wrap.status('sol')
        self.assertEqual(json.loads(out.getvalue())['worlds'][0]['sol']['status'],'technical_error')
        self.assertIsNone(json.loads(out.getvalue())['worlds'][0]['sol']['result'])

if __name__=='__main__':unittest.main()
