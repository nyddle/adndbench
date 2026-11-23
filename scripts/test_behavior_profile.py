import unittest
from unittest.mock import patch
from types import SimpleNamespace
from scripts.behavior_profile import summarize, public_result, markdown, scenario_for_split, SCENARIOS, extract

class BehaviorProfileTest(unittest.TestCase):
    def test_expanded_runs_have_unique_conditions(self):
        names = [name for _, _, name in SCENARIOS]
        self.assertEqual(len(names), len(set(names)))
        for name in ('expanded-memory-s8', 'expanded-quest-extreme', 'full-hard-3-parallel'):
            self.assertIn(name, names)

    def test_parallel_budget_stop_is_a_note_not_a_game_outcome(self):
        from scripts.parallel_gradient_calibration import INPUT_RESERVE
        plan = {'axis':'radical-adventure', 'level':'custom', 'reasoning_effort':'low',
                'context_turns':10, 'cli_version':'test', 'adapter':'radical',
                'max_actions_per_game':100, 'max_input_tokens_per_split':INPUT_RESERVE,
                'parallel_migration':{'sequential_dev_receipts':3}}
        state = {'episodes':{'episode':{'status':'ready','turns':[]}},
                 'receipts':{'dev':[{'status':'completed','usage':{'input_tokens':1}}]}}
        fake = SimpleNamespace(load=lambda name: (None,plan,state),
                specs=lambda p,split: [(1,'private','gpt-6-luna')],
                key_for=lambda split,world,model: 'episode')
        with patch('scripts.behavior_profile.configured', return_value=fake):
            result = extract('parallel_integrated','example','dev')
        self.assertIn('остановлены при достижении бюджета', result['execution_note'])
        self.assertEqual(result['episodes'][0]['status'], 'ready')
        self.assertIsNone(result['episodes'][0]['score'])
        self.assertIsNone(result['episodes'][0]['result'])

    def test_terminal_denominator_excludes_incomplete_and_failure_is_not_success(self):
        episodes = [
            {'model':'m','status':'completed','result':{'terminal_reason':'completed','turns':10,'invalid_actions':0},'score':100},
            {'model':'m','status':'completed','result':{'terminal_reason':'incorrect_code','turns':4,'invalid_actions':2},'score':30},
            {'model':'m','status':'action_limit','result':{'terminal_reason':None,'turns':50,'invalid_actions':9},'score':None},
            {'model':'m','status':'inflight','result':None,'score':None},
        ]
        out=summarize(episodes,'m')
        self.assertEqual((out['planned'],out['terminal'],out['wins']), (4,2,1))
        self.assertEqual((out['win_rate'],out['mean_turns_terminal'],out['mean_invalid_terminal'],out['mean_score_terminal']),(.5,7,1,65))
        self.assertEqual(out['statuses']['action_limit'],1)
        self.assertEqual(summarize(episodes,'other')['win_rate'],None)
    def test_sensitive_fields_and_companion_names_not_exported(self):
        result=public_result({'seed':'secret','clue':'secret','recruited':['A','B'],'turns':3,'rooms_visited':4})
        self.assertEqual(result,{'recruited_count':2,'turns':3,'rooms_visited':4})
    def test_absent_and_incomplete_have_no_zero_score(self):
        data={'split':'dev','scenarios':[{'label':'unavailable','available':False},
              {'label':'x','available':True,'episodes':[{'world':1,'model':'gpt-6-luna','status':'action_limit','result':{'turns':4},'score':None,'components':None}],
               'models':{m:summarize([{'world':1,'model':'gpt-6-luna','status':'action_limit','result':{'turns':4},'score':None,'components':None}],m)
                         for m in ('gpt-6-luna','gpt-6.2-sol','gpt-6.2-astra')}}]}
        report=markdown(data)
        self.assertIn('0/1 | —',report)
        self.assertIn('не запускалась',report)
        self.assertIn('unavailable',report)
        self.assertNotIn('балл: 0',report)
    def test_fresh_holdout_is_separate_from_original_development_pool(self):
        self.assertEqual(scenario_for_split('balanced','short-memory-4','dev'),('balanced','short-memory-4'))
        self.assertEqual(scenario_for_split('balanced','short-memory-4','holdout'),('balanced','short-memory-4-fresh-holdout'))
        self.assertEqual(scenario_for_split('balanced','another-plan','holdout'),('balanced','another-plan'))
        self.assertEqual(scenario_for_split('sol_memory','extension','holdout'),('pair','radical-memory-base'))

    def test_markdown_shows_source_and_split(self):
        data={'split':'holdout','scenarios':[{'label':'x','available':True,
              'plan_name':'short-memory-4-fresh-holdout','split':'holdout',
              'fork_provenance':{'source_name':'short-memory-4'}, 'episodes':[],
              'models':{m:summarize([],m) for m in ('gpt-6-luna','gpt-6.2-sol','gpt-6.2-astra')}}]}
        report=markdown(data)
        self.assertIn('`short-memory-4-fresh-holdout`',report)
        self.assertIn('исходный dev-план: `short-memory-4`',report)
        self.assertIn('выборка: `holdout`',report)

    def test_fixed_party_success_is_oracle_feasibility_not_a_battle_win(self):
        episode={'model':'m','status':'completed','result':{'terminal_reason':'completed','turns':1,'invalid_actions':0},'score':None}
        out=summarize([episode],'m','party_choice_feasible_by_oracle',fixed_case=True)
        self.assertEqual(out['successes'],1)
        self.assertIsNone(out['wins'])
        self.assertIsNone(out['win_rate'])
        self.assertIsNone(out['success_rate'])
        battle=summarize([episode],'m','model_played_combat',fixed_case=True)
        self.assertEqual(battle['wins'],1)
        self.assertIsNone(battle['win_rate'])
        self.assertIsNone(battle['success_rate'])

    def test_party_and_combat_telemetry_is_allowlisted_without_seed(self):
        output=public_result({'selected':'mage','hero_hp':3,'damage_dealt':15,'healing':4,'charges_used':2,'seed':'hidden'})
        self.assertEqual(output,{'selected':'mage','hero_hp':3,'damage_dealt':15,'healing':4,'charges_used':2})

if __name__ == '__main__': unittest.main()
