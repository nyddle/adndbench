import contextlib
import fcntl
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import independent_gradient_calibration as sequential
from scripts import parallel_gradient_calibration as parallel
from scripts.migrate_gradient_to_parallel import migrate

class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        e=sequential.engine;r=sequential.radical
        patches=[patch.object(sequential,'BASE',Path(self.tmp.name)/'seq'),patch.object(parallel,'BASE',Path(self.tmp.name)/'parallel'),
                 patch.multiple(e,BASE=e.BASE,MODELS=e.MODELS,fingerprint=e.fingerprint,create_game=e.create_game,
                                rule=e.rule,actions=e.actions,canonical_action=e.canonical_action,status=e.status,prompt=e.prompt),
                 patch.object(r,'fingerprint',r.fingerprint),patch.object(r,'rule',r.rule),
                 patch.object(e,'cli_version',return_value='test-cli')]
        for p in patches:p.start();self.addCleanup(p.stop)
        sequential.configure()
        config={'memory':'medium','navigation':'easy','quests':'hard','combat':'medium','party':True,'max_turns':1}
        with contextlib.redirect_stdout(io.StringIO()):r.init('source',config,1,1,1,10,10000,1)

    def test_fork_preserves_replay_receipts_budgets_without_calls(self):
        e=sequential.engine
        def call(prompt,model,timeout):
            return {'error':'tool_use_detected'} if model=='gpt-6-luna' else {'action':{'type':'talk'},'usage':{'input_tokens':1}}
        with patch.object(e,'call',side_effect=call),contextlib.redirect_stdout(io.StringIO()):sequential.run('source','dev')
        sequential.configure();_,before_p,before_s=e.load('source')
        with patch.object(e,'call',side_effect=AssertionError('unexpected model call')),contextlib.redirect_stdout(io.StringIO()):migrate('source','fork')
        parallel.configure();_,p,s=e.load('fork')
        self.assertEqual(p['seeds'],before_p['seeds']);self.assertEqual(p['system_prompt'],before_p['system_prompt'])
        self.assertEqual(p['game_config'],before_p['game_config']);self.assertEqual(s['receipts'],before_s['receipts'])
        self.assertEqual(s['episodes'],before_s['episodes']);self.assertEqual(p['parallel_migration']['sequential_dev_receipts'],3)
        self.assertEqual(p['max_calls_per_split'],before_p['max_calls_per_split'])
        self.assertEqual(p['max_input_tokens_per_split'],before_p['max_input_tokens_per_split'])
        sequential.configure();_,original,after=e.load('source');self.assertEqual(original,before_p);self.assertEqual(after,before_s)
        with self.assertRaises(FileExistsError):migrate('source','fork')

    def test_refuses_active_source_or_unresolved_receipt(self):
        e=sequential.engine;d,p,s=e.load('source')
        fd=os.open(d/'.lock',os.O_CREAT|os.O_RDWR,0o600)
        with os.fdopen(fd,'r+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):migrate('source','fork')
        sequential.configure();d,p,s=e.load('source')
        s['receipts']['dev'].append({'episode':e.key_for('dev',1,'gpt-6-luna'),'number':1,'status':'inflight'})
        e.write(d/'state.json',s)
        with self.assertRaises(ValueError):migrate('source','fork')

    def test_refuses_mismatched_replay_and_inflight_episode(self):
        e=sequential.engine;d,p,s=e.load('source')
        s['episodes'][e.key_for('dev',1,'gpt-6-luna')]={'status':'inflight','turns':[]};e.write(d/'state.json',s)
        with self.assertRaises(ValueError):migrate('source','fork')
        sequential.configure();d,p,s=e.load('source');r=s['episodes'][e.key_for('dev',1,'gpt-6-luna')]
        r['status']='ready';r['turns']=[{'observation_sha256':'wrong','action':{'type':'talk'}}];e.write(d/'state.json',s)
        with self.assertRaises(ValueError):migrate('source','fork')

if __name__=='__main__':unittest.main()
