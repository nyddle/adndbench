import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import continue_balanced_holdout as c

class ContinueBalancedTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.patcher=patch.object(c.balanced,'BASE',Path(self.tmp.name));self.patcher.start();self.addCleanup(self.patcher.stop)
        self.cli=patch.object(c.balanced.engine,'cli_version',return_value='test-cli');self.cli.start();self.addCleanup(self.cli.stop)
        self.status=patch.object(c.independent.gradient,'status',c.independent.gradient.status);self.status.start();self.addCleanup(self.status.stop)
        c.balanced.configure('s4');e=c.balanced.engine
        with contextlib.redirect_stdout(io.StringIO()):
            c.balanced.middle.init('trial',1,1,8,40,100000,8)
        d,p,s=e.load('trial');s['sealed']=True;s['sealed_plan_sha256']=e.digest(p)
        key=e.key_for('holdout',1,c.balanced.MODELS[0]);s['episodes'][key]={'status':'technical_error','technical_error':'turn_failed','turns':[]}
        s['receipts']['holdout'].append({'episode':key,'number':1,'status':'technical_error'})
        e.write(d/'state.json',s)

    def test_skip_failure_and_preserve_plan_and_budget(self):
        e=c.balanced.engine
        original=e.load('trial')[1]
        def call(prompt,model,timeout):
            self.assertNotEqual(model,c.balanced.MODELS[0])
            return {'action':{'type':'invalid'},'usage':{'input_tokens':1}}
        with patch.object(e,'call',side_effect=call) as mock,contextlib.redirect_stdout(io.StringIO()):c.run('trial')
        d,p,s=e.load('trial');self.assertEqual(original,p)
        self.assertEqual(s['episodes'][e.key_for('holdout',1,c.balanced.MODELS[0])]['status'],'technical_error')
        self.assertEqual({x.args[1] for x in mock.call_args_list},set(c.balanced.MODELS[1:]))
        self.assertLessEqual(len(s['receipts']['holdout']),p['max_calls_per_split'])
        self.assertTrue((d/'holdout-continuation-audit.json').exists())
        with self.assertRaises(ValueError):c.run('trial')

    def test_inflight_blocks_every_call(self):
        e=c.balanced.engine;d,p,s=e.load('trial')
        s['episodes'][e.key_for('holdout',1,c.balanced.MODELS[1])]={'status':'inflight','turns':[]};e.write(d/'state.json',s)
        with patch.object(e,'call',side_effect=AssertionError('retried')):
            with self.assertRaises(ValueError):c.run('trial')

if __name__=='__main__':unittest.main()
