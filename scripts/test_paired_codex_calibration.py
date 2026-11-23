import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import paired_codex_calibration as pilot


class TinyGame:
    def __init__(self, seed): self.seed=seed; self.turn=0; self.done=False
    def observe(self): return {'turn':self.turn,'done':self.done,'public_action':'step'}
    def step(self, action):
        self.turn+=1; self.done=self.turn>=2; return self.observe()
    def result(self): return {'terminal_reason':'completed' if self.done else None,'turns':self.turn,'seed':self.seed}


class PairedTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.patches=[patch.object(pilot,'BASE',Path(self.tmp.name)),patch.object(pilot,'cli_version',return_value='test-cli'),
                      patch.object(pilot,'fingerprint',return_value='source-hash'),
                      patch.object(pilot,'create_game',side_effect=lambda p, seed:TinyGame(seed)),
                      patch.object(pilot,'rule',return_value='rules'),
                      patch.object(pilot,'actions',return_value=[{'type':'step'}])]
        for p in self.patches:p.start();self.addCleanup(p.stop)
    def initialize(self, name='p', **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            pilot.init(name,'hard_memory_navigation','navigation','base',kwargs.get('dev',1),kwargs.get('hold',1),
                       kwargs.get('actions',10),kwargs.get('calls',20),kwargs.get('tokens',1000),10)
    @staticmethod
    def answer(text, model, timeout): return {'action':{'type':'step'},'usage':{'input_tokens':10,'output_tokens':2}}

    def test_balanced_pairs_seed_privacy_seal_and_replay(self):
        self.initialize()
        d,p,st=pilot.load('p')
        self.assertEqual(len(set(p['seeds']['dev']+p['seeds']['holdout'])),2)
        self.assertEqual(os.stat(d/'plan.json').st_mode & 0o077,0)
        with self.assertRaises(ValueError):pilot.run('p','holdout')
        with patch.object(pilot,'call',side_effect=self.answer) as call,contextlib.redirect_stdout(io.StringIO()):pilot.run('p','dev')
        self.assertEqual([x.args[1] for x in call.call_args_list],list(pilot.MODELS)*2)
        with contextlib.redirect_stdout(io.StringIO()):pilot.seal('p')
        with self.assertRaises(ValueError):pilot.run('p','dev')
        with patch.object(pilot,'call',side_effect=self.answer),contextlib.redirect_stdout(io.StringIO()):pilot.run('p','holdout')
        out=io.StringIO()
        with contextlib.redirect_stdout(out):pilot.status('p')
        report=json.loads(out.getvalue())
        self.assertEqual(report['groups'][0]['paired_outcomes']['both'],1)
        self.assertEqual(report['groups'][1]['paired_outcomes']['both'],1)
        for seed in p['seeds']['dev']+p['seeds']['holdout']:self.assertNotIn(seed,out.getvalue())
        state=json.loads((d/'state.json').read_text())
        self.assertEqual(len(state['receipts']['dev']),4)
        self.assertEqual({r['status'] for r in state['episodes'].values()},{'completed'})
        state['episodes'][next(iter(state['episodes']))]['turns'][0]['observation_sha256']='0'*64
        pilot.write(d/'state.json',state)
        with self.assertRaises(ValueError):
            with contextlib.redirect_stdout(io.StringIO()):pilot.status('p')

    def test_failure_is_not_retried_or_counted_as_defeat(self):
        self.initialize()
        with patch.object(pilot,'call',return_value={'error':'timeout'}) as call,contextlib.redirect_stdout(io.StringIO()):pilot.run('p','dev')
        self.assertEqual(call.call_count,1)
        out=io.StringIO()
        with contextlib.redirect_stdout(out):pilot.status('p')
        data=json.loads(out.getvalue())['groups'][0]
        self.assertEqual(data['paired_outcomes']['incomplete'],1)
        self.assertEqual(data['models'][pilot.MODELS[0]]['successes'],0)
        with self.assertRaises(ValueError):pilot.run('p','dev')
        with self.assertRaises(ValueError):pilot.seal('p')

    def test_budget_stops_and_does_not_convert_pending_to_failures(self):
        self.initialize(calls=3)
        with patch.object(pilot,'call',side_effect=self.answer) as call,contextlib.redirect_stdout(io.StringIO()):pilot.run('p','dev')
        self.assertEqual(call.call_count,3)
        out=io.StringIO()
        with contextlib.redirect_stdout(out):pilot.status('p')
        data=json.loads(out.getvalue())['groups'][0]
        self.assertEqual(data['calls'],3)
        self.assertEqual(data['paired_outcomes']['incomplete'],1)
        with self.assertRaises(ValueError):pilot.seal('p')

    def test_parse_rejects_tools_and_missing_usage(self):
        good=[{'type':'item.completed','item':{'type':'agent_message','text':'{"type":"step"}'}},
              {'type':'turn.completed','usage':{'input_tokens':10}}]
        enc=lambda items:'\n'.join(json.dumps(x) for x in items)
        self.assertEqual(pilot.parse_events(enc(good))['action'],{'type':'step'})
        self.assertEqual(pilot.parse_events(enc(good[:-1]))['error'],'missing_usage')
        tool={'type':'item.started','item':{'type':'command_execution'}}
        self.assertEqual(pilot.parse_events(enc([tool]+good))['error'],'tool_use_detected')

    def test_fingerprint_tracks_only_relevant_sources(self):
        # Exercise the real fingerprint separately from the mocked plan tests.
        self.patches[2].stop()
        folder=Path(self.tmp.name)/'benchmark'
        folder.mkdir(parents=True)
        for name in ('__init__.py','fixed_probes.py','vector_harness.py','hard_memory_navigation.py','quest_trial.py'):
            (folder/name).write_text('original')
        with patch.object(pilot,'ROOT',Path(self.tmp.name)):
            original=pilot.fingerprint('hard_memory_navigation')
            (folder/'unrelated.py').write_text('new')
            self.assertEqual(pilot.fingerprint('hard_memory_navigation'),original)
            (folder/'quest_trial.py').write_text('changed')
            self.assertEqual(pilot.fingerprint('hard_memory_navigation'),original)
            (folder/'hard_memory_navigation.py').write_text('changed')
            self.assertNotEqual(pilot.fingerprint('hard_memory_navigation'),original)

    def test_memory_requires_window_and_actions_sufficient_to_complete(self):
        with self.assertRaises(ValueError):
            pilot.init('m','hard_memory_navigation','memory','extreme',1,1,40,100,10000,40)

if __name__=='__main__': unittest.main()
