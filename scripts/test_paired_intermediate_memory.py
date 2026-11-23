import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import paired_intermediate_memory as wrap


class IntermediateRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.e=wrap.engine
        self.patches=[patch.object(self.e,'BASE',Path(self.tmp.name)),patch.object(self.e,'fingerprint',wrap.fingerprint),
                      patch.object(self.e,'create_game',wrap.create_game),patch.object(self.e,'rule',wrap.rule),
                      patch.object(self.e,'actions',wrap.actions),patch.object(self.e,'cli_version',return_value='test-cli')]
        for p in self.patches:p.start();self.addCleanup(p.stop)
    def init(self, **kw):
        with contextlib.redirect_stdout(io.StringIO()):
            wrap.init('test',1,1,kw.get('actions',10),kw.get('calls',30),100000,kw.get('context',10))
    def test_real_episode_common_world_private_and_sealed(self):
        self.init();d,p,_=self.e.load('test')
        self.assertEqual(os.stat(d/'plan.json').st_mode&0o077,0)
        self.assertNotEqual(p['seeds']['dev'][0],p['seeds']['holdout'][0])
        def call(text,model,timeout):
            self.assertNotIn(p['seeds']['dev'][0],text)
            public=json.loads(text.split('\n',1)[1]);obs=public['current_observation']
            if obs['location']!='ворота':a={'type':'move','direction':'forward'}
            else:
                history=[e['observation'] for e in public['past_turns']]
                initial=history[0]['assignments']; values={x['person']:x['item'] for x in initial}
                for old in history[1:]:
                    for event in old.get('events',[]):
                        x,y=event['people'];values[x],values[y]=values[y],values[x]
                owner=next(k for k,v in values.items() if v==obs['query']['item'])
                a={'type':'deliver','person':owner}
            return {'action':a,'usage':{'input_tokens':1}}
        with patch.object(self.e,'call',side_effect=call) as mocked,contextlib.redirect_stdout(io.StringIO()):self.e.run('test','dev')
        self.assertEqual(mocked.call_count,12)
        out=io.StringIO()
        with contextlib.redirect_stdout(out):self.e.status('test')
        report=json.loads(out.getvalue());self.assertEqual(report['groups'][0]['paired_outcomes']['both'],1)
        self.assertNotIn(p['seeds']['dev'][0],out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):self.e.seal('test')
        with self.assertRaises(ValueError):self.e.run('test','dev')
    def test_guard_rejects_missing_clue_or_insufficient_actions(self):
        with self.assertRaises(ValueError):self.init(actions=5)
        with self.assertRaises(ValueError):self.init(actions=10,context=6)
    def test_network_failure_is_recorded_and_not_retried(self):
        self.init()
        with patch.object(self.e,'call',return_value={'error':'timeout'}) as mocked,contextlib.redirect_stdout(io.StringIO()):self.e.run('test','dev')
        self.assertEqual(mocked.call_count,1)
        with self.assertRaises(ValueError):self.e.run('test','dev')

if __name__=='__main__':unittest.main()
