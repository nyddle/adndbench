import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import gradient_codex_calibration as gradient


class FakeGame:
    def __init__(self,seed):self.seed=seed;self.done=False;self.outcome=None;self.points=None
    def observe(self):return {'done':self.done,'turn':int(self.done)}
    def step(self,action):
        self.done=True;self.points={'luna':20,'sol':50,'astra':100}[action['type']]
        self.outcome='completed' if self.points==100 else 'death'
    def result(self):return {'terminal_reason':self.outcome,'seed':self.seed}


class GradientTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.e=gradient.engine
        # configure changes globals only in this test process; patch saves all
        # preexisting globals so tests never affect other executor invocations.
        self.patches=[patch.object(gradient,'BASE',Path(self.tmp.name)),
                      patch.multiple(self.e,BASE=self.e.BASE,MODELS=self.e.MODELS,
                                     fingerprint=self.e.fingerprint,create_game=self.e.create_game,
                                     rule=self.e.rule,actions=self.e.actions,
                                     canonical_action=self.e.canonical_action,status=self.e.status,prompt=self.e.prompt),
                      patch.object(gradient.radical,'fingerprint',gradient.radical.fingerprint),
                      patch.object(gradient.radical,'rule',gradient.radical.rule),
                      patch.object(self.e,'cli_version',return_value='test-cli')]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        gradient.configure()
        self.config={'memory':'medium','navigation':'easy','quests':'medium','combat':'off','party':False,'max_turns':20}
        with contextlib.redirect_stdout(io.StringIO()):gradient.radical.init('test',self.config,1,1,2,6,10000,2)
        self.e.create_game=lambda p,seed:FakeGame(seed)
        self.e.actions=lambda p,obs:[{'type':'luna'},{'type':'sol'},{'type':'astra'}]

    def test_compaction_preserves_unique_facts_actions_and_current_observation(self):
        config={**self.config,'combat':'hard','party':True,'max_turns':40}
        p={'adapter':'radical_adventure','game_config':config}
        game=gradient.radical.create_game(p,'dev-public')
        history=[]
        for i in range(12):
            obs=game.observe()
            action={'type':'talk'} if i==0 else {'type':'move','direction':'invalid'}
            history.append({'observation':obs,'action':action})
            game.step(action)
        current=game.observe(); original=copy.deepcopy(history)
        compact=gradient.compact_history(history,current)
        self.assertEqual(history,original)
        self.assertEqual(len(compact),len(history))
        self.assertTrue(any('runes' in e['observation']['notice'] for e in compact))
        for i,(before,after) in enumerate(zip(history,compact)):
            self.assertEqual(before['action'],after['action'])
            for key,value in before['observation'].items():
                if key not in after['observation']:
                    self.assertIn(key,gradient.HISTORY_FIELDS)
                    self.assertEqual(value,current[key])
                    self.assertTrue(any(old['observation'].get(key)==value for old in history[:i]))
                else:self.assertEqual(after['observation'][key],value)
        p.update(context_turns=40,system_prompt=gradient.rule(p))
        with patch.object(self.e,'actions',gradient.radical.actions):
            prompt=gradient.prompt(p,history,current)
        sent=json.loads(prompt.split('\n',1)[1])
        self.assertEqual(sent['current_observation'],current)
        self.assertEqual(sent['past_turns'],compact)
        full=len(json.dumps(history,ensure_ascii=False).encode())
        smaller=len(json.dumps(compact,ensure_ascii=False).encode())
        self.assertLess(smaller,full*0.6)

    def test_compaction_keeps_first_occurrence_of_changed_values(self):
        history=[{'observation':{'tasks':[{'id':'A'}],'notice':i},'action':{'type':'x'}} for i in range(2)]
        history += [{'observation':{'tasks':[{'id':'B'}],'notice':i},'action':{'type':'x'}} for i in range(2,4)]
        compact=gradient.compact_history(history,{'tasks':[{'id':'B'}]})
        self.assertIn('tasks',compact[0]['observation'])
        self.assertIn('tasks',compact[1]['observation'])  # value differs from current
        self.assertIn('tasks',compact[2]['observation'])  # first occurrence
        self.assertNotIn('tasks',compact[3]['observation'])
        self.assertEqual([x['observation']['notice'] for x in compact],[0,1,2,3])

    def test_reappearance_after_change_is_preserved(self):
        history=[{'observation':{'tasks':[{'id':c}]},'action':{'type':'x'}} for c in ('A','B','A','A')]
        compact=gradient.compact_history(history,{'tasks':[{'id':'A'}]})
        self.assertIn('tasks',compact[0]['observation'])
        self.assertIn('tasks',compact[1]['observation'])
        self.assertIn('tasks',compact[2]['observation'])
        self.assertNotIn('tasks',compact[3]['observation'])

    def test_three_paired_scores_and_no_seed_leak(self):
        def call(text,model,timeout):
            return {'action':{'type':{'gpt-6-luna':'luna','gpt-6.2-sol':'sol','gpt-6.2-astra':'astra'}[model]},
                    'usage':{'input_tokens':10}}
        with patch.object(gradient.radical_score,'score',side_effect=lambda game,actions:{'score':game.points}),\
             patch.object(self.e,'call',side_effect=call) as m,contextlib.redirect_stdout(io.StringIO()):
            self.e.run('test','dev')
        self.assertEqual([x.args[1] for x in m.call_args_list],list(gradient.MODELS))
        out=io.StringIO()
        with patch.object(gradient.radical_score,'score',side_effect=lambda game,actions:{'score':game.points}),contextlib.redirect_stdout(out):
            gradient.status('test')
        report=json.loads(out.getvalue()); group=report['groups'][0]
        self.assertEqual(group['complete_worlds']['strict_ascending'],1)
        self.assertEqual([group['models'][name]['mean_terminal_score'] for name in gradient.MODELS],[20,50,100])
        _,plan,_=self.e.load('test')
        self.assertNotIn(plan['seeds']['dev'][0],out.getvalue())

    def test_real_adventure_score_replays_terminal_model_actions(self):
        config={**self.config, 'max_turns':1}
        with contextlib.redirect_stdout(io.StringIO()):
            gradient.radical.init('real',config,1,1,1,3,10000,1)
        def call(text,model,timeout):
            return {'action':{'type':'talk'},'usage':{'input_tokens':1}}
        with patch.object(self.e,'create_game',gradient.radical.create_game), \
             patch.object(self.e,'actions',gradient.radical.actions), \
             patch.object(self.e,'call',side_effect=call),contextlib.redirect_stdout(io.StringIO()):
            self.e.run('real','dev')
        out=io.StringIO()
        with patch.object(self.e,'create_game',gradient.radical.create_game), \
             patch.object(self.e,'actions',gradient.radical.actions),contextlib.redirect_stdout(out):
            gradient.status('real')
        group=json.loads(out.getvalue())['groups'][0]
        self.assertEqual(group['complete_worlds']['all_terminal'],1)
        for model in gradient.MODELS:
            self.assertEqual(group['models'][model]['terminal_reasons'],{'turn_limit':1})
            self.assertIsInstance(group['models'][model]['mean_terminal_score'],(int,float))

    def test_incomplete_scores_are_not_zero_or_aggregated(self):
        with patch.object(self.e,'call',return_value={'error':'timeout'}),contextlib.redirect_stdout(io.StringIO()):
            self.e.run('test','dev')
        out=io.StringIO()
        with contextlib.redirect_stdout(out):gradient.status('test')
        group=json.loads(out.getvalue())['groups'][0]
        self.assertEqual(group['complete_worlds']['incomplete'],1)
        for model in gradient.MODELS:
            self.assertIsNone(group['models'][model]['mean_terminal_score'])
            self.assertIsNone(group['worlds'][0]['models'][model]['score'])

if __name__=='__main__':unittest.main()
