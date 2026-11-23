import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import three_model_balanced_memory as wrap


class BalancedRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        e=wrap.engine;m=wrap.middle
        self.patches=[patch.object(wrap,'BASE',Path(self.tmp.name)),
          patch.multiple(e,BASE=e.BASE,MODELS=e.MODELS,fingerprint=e.fingerprint,create_game=e.create_game,
                         rule=e.rule,actions=e.actions,status=e.status),
          patch.multiple(m,BASE=m.BASE,ADAPTER=m.ADAPTER,AXIS=m.AXIS,LEVEL=m.LEVEL,
                         MIN_ACTIONS=m.MIN_ACTIONS,EXTRA_ALLOWED_ACTIONS=m.EXTRA_ALLOWED_ACTIONS,
                         fingerprint=m.fingerprint,module=m.module),
          patch.object(e,'cli_version',return_value='test-cli')]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        wrap.configure('s4')
    def initialize(self, worlds=2):
        with contextlib.redirect_stdout(io.StringIO()):wrap.middle.init('test',worlds,1,8,30,100000,8)
    def test_three_models_two_shared_worlds_and_development_holdout(self):
        self.initialize();d,p,_=wrap.engine.load('test');self.assertEqual(p['models'],list(wrap.MODELS))
        self.assertFalse(set(p['seeds']['dev'])&set(p['seeds']['holdout']))
        self.assertEqual(len(p['seeds']['dev']),2);initial_observations=[]
        def call(text,model,timeout):
            for seed in p['seeds']['dev']+p['seeds']['holdout']:self.assertNotIn(seed,text)
            content=json.loads(text.split('\n',1)[1]);obs=content['current_observation']
            if obs['turn']==0:initial_observations.append((model,obs))
            if obs['location']!='ворота':action={'type':'move','direction':'forward'}
            else:
                hist=[x['observation'] for x in content['past_turns']]
                holdings={x['person']:x['item'] for x in hist[0]['assignments']}
                for previous in hist:
                    for event in previous.get('events',[]):
                        x,y=event['people'];holdings[x],holdings[y]=holdings[y],holdings[x]
                owner=next(k for k,v in holdings.items() if v==obs['query']['item'])
                action={'type':'deliver','person':owner}
            return {'action':action,'usage':{'input_tokens':1}}
        with patch.object(wrap.engine,'call',side_effect=call) as mock,contextlib.redirect_stdout(io.StringIO()):
            wrap.engine.run('test','dev')
        self.assertEqual(mock.call_count,24)
        for i in (0,3):
            self.assertEqual([x[0] for x in initial_observations[i:i+3]],list(wrap.MODELS))
            self.assertEqual(initial_observations[i][1],initial_observations[i+1][1])
            self.assertEqual(initial_observations[i][1],initial_observations[i+2][1])
        out=io.StringIO()
        with contextlib.redirect_stdout(out):wrap.status('test')
        report=json.loads(out.getvalue());self.assertEqual(report['groups'][0]['complete_triples'],2)
        self.assertEqual([report['groups'][0]['models'][m]['correct'] for m in wrap.MODELS],[2,2,2])
        for seed in p['seeds']['dev']+p['seeds']['holdout']:self.assertNotIn(seed,out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):wrap.engine.seal('test')
        with self.assertRaises(ValueError):wrap.engine.run('test','dev')
    def test_incomplete_and_technical_are_not_counted_as_wrong(self):
        self.initialize(worlds=1)
        with patch.object(wrap.engine,'call',return_value={'error':'timeout'}) as mock,contextlib.redirect_stdout(io.StringIO()):wrap.engine.run('test','dev')
        self.assertEqual(mock.call_count,1)
        out=io.StringIO()
        with contextlib.redirect_stdout(out):wrap.status('test')
        report=json.loads(out.getvalue());self.assertEqual(report['groups'][0]['complete_triples'],0)
        for model in wrap.MODELS:self.assertIsNone(report['groups'][0]['models'][model]['accuracy_terminal'])
        with self.assertRaises(ValueError):wrap.engine.run('test','dev')
    def test_window_prevents_losing_initial_clue(self):
        with self.assertRaises(ValueError):wrap.middle.init('x',1,1,8,30,100000,4)

if __name__=='__main__':unittest.main()
