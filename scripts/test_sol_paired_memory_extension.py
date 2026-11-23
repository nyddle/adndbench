import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import sol_paired_memory_extension as wrap


class SolMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.parent=Path(self.tmp.name)/'parent';self.dest=Path(self.tmp.name)/'sol';self.e=wrap.engine
        self.patches=[patch.object(wrap,'PARENT_BASE',self.parent),patch.object(wrap,'BASE',self.dest),
                      patch.multiple(self.e,BASE=self.e.BASE,MODELS=self.e.MODELS,fingerprint=self.e.fingerprint,status=self.e.status),
                      patch.multiple(wrap.bridge,BASE=wrap.bridge.BASE,fingerprint=wrap.bridge.fingerprint,read_reference=wrap.bridge.read_reference),
                      patch.object(self.e,'cli_version',return_value='test-cli')]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        self.e.BASE=self.parent;self.e.MODELS=wrap.SOURCE_MODELS;self.e.fingerprint=wrap._original_fingerprint
        with contextlib.redirect_stdout(io.StringIO()):
            self.e.init('ref','hard_memory_navigation','memory-compact','base',1,1,8,20,100000,8)

    def complete_reference(self):
        d,p,st=self.e.load('ref')
        for world,seed,model in self.e.specs(p,'dev'):
            game=self.e.create_game(p,seed);journal=[]
            while not game.done:
                obs=game.observe()
                action={'type':'deliver','person':game.answer} if obs['location']=='ворота' else {'type':'move','direction':'forward'}
                journal.append({'observation_sha256':self.e.digest(obs),'action':action});game.step(action)
            st['episodes'][self.e.key_for('dev',world,model)]={'status':'completed','turns':journal,'result':game.result()}
        self.e.write(d/'state.json',st)
        return p

    def init_sol(self):
        wrap.configure_bridge()
        with contextlib.redirect_stdout(io.StringIO()):wrap.bridge.init('sol','ref')

    def test_same_dev_world_rules_and_no_holdout_copy(self):
        reference=self.complete_reference();self.init_sol();_,plan,_=self.e.load('sol')
        self.assertEqual(plan['seeds']['dev'],reference['seeds']['dev'])
        self.assertEqual(plan['seeds']['holdout'],[])
        self.assertNotIn(reference['seeds']['holdout'][0],json.dumps(plan,ensure_ascii=False))
        for f in ('system_prompt','level','axis','reasoning_effort','context_turns','max_actions_per_game','max_calls_per_split','max_input_tokens_per_split'):
            self.assertEqual(plan[f],reference[f])
        self.assertEqual(plan['models'],['gpt-6.2-sol'])
        def call(text,model,timeout):
            self.assertNotIn(plan['seeds']['dev'][0],text)
            p=json.loads(text.split('\n',1)[1]);obs=p['current_observation']
            if obs['location']!='ворота':return {'action':{'type':'move','direction':'forward'},'usage':{'input_tokens':1}}
            history=[x['observation'] for x in p['past_turns']]
            inv={x['person']:x['item'] for x in history[0]['assignments']}
            for entry in history:
                for event in entry.get('events',[]):
                    a,b=event['people'];inv[a],inv[b]=inv[b],inv[a]
            owner=next(x for x,item in inv.items() if item==obs['query']['item'])
            return {'action':{'type':'deliver','person':owner},'usage':{'input_tokens':1}}
        with patch.object(self.e,'call',side_effect=call) as mocked,contextlib.redirect_stdout(io.StringIO()):self.e.run('sol','dev')
        self.assertEqual(mocked.call_count,4)
        out=io.StringIO()
        with contextlib.redirect_stdout(out):wrap.bridge.status('sol')
        data=json.loads(out.getvalue());self.assertEqual(data['worlds'][0]['sol']['result']['terminal_reason'],'completed')
        self.assertNotIn(plan['seeds']['dev'][0],out.getvalue())
        self.e.BASE=self.parent;self.e.MODELS=wrap.SOURCE_MODELS;self.e.fingerprint=wrap._original_fingerprint
        _,_,st=self.e.load('ref');self.assertEqual({r['status'] for r in st['episodes'].values()},{'completed'})

    def test_rejects_incomplete_reference_and_never_retries_timeout(self):
        wrap.configure_bridge()
        with self.assertRaises(ValueError):wrap.bridge.init('sol','ref')
        self.assertFalse((self.dest/'sol'/'plan.json').exists())
        self.complete_reference()
        with contextlib.redirect_stdout(io.StringIO()):wrap.bridge.init('sol','ref')
        with patch.object(self.e,'call',return_value={'error':'timeout'}) as mock,contextlib.redirect_stdout(io.StringIO()):self.e.run('sol','dev')
        self.assertEqual(mock.call_count,1)
        with self.assertRaises(ValueError):self.e.run('sol','dev')

if __name__=='__main__':unittest.main()
