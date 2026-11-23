import contextlib
import io
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from scripts import parallel_gradient_calibration as parallel

class ParallelRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        e=parallel.engine;r=parallel.radical
        patches=[patch.object(parallel,'BASE',Path(self.tmp.name)),patch.object(parallel,'INPUT_RESERVE',1),
                 patch.multiple(e,BASE=e.BASE,MODELS=e.MODELS,fingerprint=e.fingerprint,create_game=e.create_game,
                                rule=e.rule,actions=e.actions,canonical_action=e.canonical_action,status=e.status,prompt=e.prompt),
                 patch.object(r,'fingerprint',r.fingerprint),patch.object(r,'rule',r.rule),
                 patch.object(e,'cli_version',return_value='test-cli')]
        for p in patches:p.start();self.addCleanup(p.stop)
        parallel.configure()
        config={'memory':'medium','navigation':'easy','quests':'hard','combat':'medium','party':True,'max_turns':1}
        with contextlib.redirect_stdout(io.StringIO()):r.init('trial',config,2,1,1,10,10000,1)

    def test_parallel_calls_do_not_retry_and_each_episode_is_recorded(self):
        e=parallel.engine;mutex=threading.Lock();active=0;peak=0
        def call(prompt,model,timeout):
            nonlocal active,peak
            with mutex:active+=1;peak=max(peak,active)
            time.sleep(.03)
            with mutex:active-=1
            if model=='gpt-6-luna':return {'error':'tool_use_detected'}
            return {'action':{'type':'talk'},'usage':{'input_tokens':1}}
        with patch.object(e,'call',side_effect=call) as mock,contextlib.redirect_stdout(io.StringIO()):parallel.run('trial','dev')
        self.assertGreater(peak,1);self.assertLessEqual(peak,parallel.WORKERS)
        self.assertEqual(mock.call_count,6)
        _,_,s=e.load('trial')
        for w in (1,2):
            self.assertEqual(s['episodes'][e.key_for('dev',w,'gpt-6-luna')]['status'],'technical_error')
            for model in ('gpt-6.2-sol','gpt-6.2-astra'):
                self.assertEqual(s['episodes'][e.key_for('dev',w,model)]['status'],'completed')
        with patch.object(e,'call',side_effect=AssertionError('retry')),contextlib.redirect_stdout(io.StringIO()):parallel.run('trial','dev')
        self.assertEqual(len(e.load('trial')[2]['receipts']['dev']),6)

    def test_inflight_is_not_retried(self):
        e=parallel.engine;d,p,s=e.load('trial');s['episodes'][e.key_for('dev',1,'gpt-6-luna')]={'status':'inflight','turns':[]};e.write(d/'state.json',s)
        with patch.object(e,'call',side_effect=AssertionError('unexpected call')):
            with self.assertRaises(ValueError):parallel.run('trial','dev')

    def test_call_limit_leaves_other_episodes_incomplete(self):
        e=parallel.engine
        config={'memory':'medium','navigation':'easy','quests':'hard','combat':'medium','party':True,'max_turns':5}
        with contextlib.redirect_stdout(io.StringIO()):parallel.radical.init('limited',config,1,1,5,4,10000,5)
        def call(prompt,model,timeout):return {'action':{'type':'talk'},'usage':{'input_tokens':1}}
        with patch.object(e,'call',side_effect=call) as mock,contextlib.redirect_stdout(io.StringIO()):parallel.run('limited','dev')
        self.assertEqual(mock.call_count,4)
        _,_,s=e.load('limited');self.assertEqual(len(s['receipts']['dev']),4)
        self.assertTrue(all(r['status']=='ready' for r in s['episodes'].values()))
        for rec in s['episodes'].values():self.assertNotIn('result',rec)

    def test_input_reservation_stops_before_launching_over_budget(self):
        e=parallel.engine
        config={'memory':'medium','navigation':'easy','quests':'hard','combat':'medium','party':True,'max_turns':2}
        with contextlib.redirect_stdout(io.StringIO()):parallel.radical.init('tokens',config,1,1,2,10,6,2)
        def call(prompt,model,timeout):return {'action':{'type':'talk'},'usage':{'input_tokens':3}}
        with patch.object(parallel,'INPUT_RESERVE',3),patch.object(e,'call',side_effect=call) as mock,contextlib.redirect_stdout(io.StringIO()):parallel.run('tokens','dev')
        self.assertEqual(mock.call_count,2)
        _,_,s=e.load('tokens')
        self.assertEqual(sum(r['usage']['input_tokens'] for r in s['receipts']['dev']),6)
        self.assertTrue(all(r['status']=='ready' for r in s['episodes'].values()))

if __name__=='__main__':unittest.main()
