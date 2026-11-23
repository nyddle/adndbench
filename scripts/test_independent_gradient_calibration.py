import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import independent_gradient_calibration as independent

class IndependentRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        e=independent.engine;g=independent.gradient;r=independent.radical
        patches=[patch.object(independent,'BASE',Path(self.tmp.name)),
                 patch.multiple(e,BASE=e.BASE,MODELS=e.MODELS,fingerprint=e.fingerprint,create_game=e.create_game,
                                rule=e.rule,actions=e.actions,canonical_action=e.canonical_action,status=e.status,prompt=e.prompt),
                 patch.object(r,'fingerprint',r.fingerprint),patch.object(r,'rule',r.rule),
                 patch.object(e,'cli_version',return_value='test-cli')]
        for p in patches:p.start();self.addCleanup(p.stop)
        independent.configure()
        config={'memory':'medium','navigation':'easy','quests':'hard','combat':'medium','party':True,'max_turns':1}
        with contextlib.redirect_stdout(io.StringIO()):r.init('trial',config,1,1,1,10,10000,1)

    def test_technical_failure_does_not_retry_or_block_other_models(self):
        e=independent.engine
        def call(prompt,model,timeout):
            if model=='gpt-6-luna':return {'error':'tool_use_detected'}
            return {'action':{'type':'talk'},'usage':{'input_tokens':1}}
        out=io.StringIO()
        with patch.object(e,'call',side_effect=call) as mock,contextlib.redirect_stdout(out):
            independent.run('trial','dev')
        self.assertEqual([x.args[1] for x in mock.call_args_list],list(independent.gradient.MODELS))
        _,_,s=e.load('trial')
        self.assertEqual(s['episodes'][e.key_for('dev',1,'gpt-6-luna')]['status'],'technical_error')
        for model in ('gpt-6.2-sol','gpt-6.2-astra'):
            self.assertEqual(s['episodes'][e.key_for('dev',1,model)]['status'],'completed')
        with patch.object(e,'call',side_effect=AssertionError('unexpected retry')),contextlib.redirect_stdout(io.StringIO()):
            independent.run('trial','dev')
        self.assertEqual(len(e.load('trial')[2]['receipts']['dev']),3)

    def test_inflight_attempt_is_never_retried(self):
        e=independent.engine;d,p,s=e.load('trial');s['episodes'][e.key_for('dev',1,'gpt-6-luna')]={'status':'inflight','turns':[]};e.write(d/'state.json',s)
        with patch.object(e,'call',side_effect=AssertionError('unexpected call')):
            with self.assertRaises(ValueError):independent.run('trial','dev')

if __name__=='__main__':unittest.main()
