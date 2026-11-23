import copy
import unittest
from benchmark.radical_adventure import Game, shortest_directions
from benchmark.radical_score import score,required_task_ids
from benchmark.quest_trial import _legal
from benchmark.party_combat import shortest_victory


class RadicalScoreTests(unittest.TestCase):
    def test_mandatory_closure_includes_consumed_item_producers(self):
        plan={'goal':'G','initial_inventory':[], 'tasks':[
            {'id':'G','requires':[],'consumes':['key'],'produces':[]},
            {'id':'A','requires':[],'consumes':[],'produces':['key']},
            {'id':'B','requires':[],'consumes':[],'produces':['other']}]}
        self.assertEqual(required_task_ids(plan),{'A','G'})
        plan['tasks'].append({'id':'C','requires':[],'consumes':[],'produces':['key']})
        with self.assertRaises(ValueError):required_task_ids(plan)

    def _play(self,combat):
        game=Game('score-test',quests='hard',combat=combat,party=True,navigation='medium')
        actions=[];points=[]
        def do(a):
            game.step(a);actions.append(a);points.append(score(game,actions)['provisional_score'])
        def travel(p):
            for direction in shortest_directions(game.edges,game.position,p):do({'type':'move','direction':direction})
        do({'type':'talk'})
        if combat=='hard':
            mage=next(p for p,roles in game.candidates.items() if 'mage' in roles)
            travel(mage);do({'type':'recruit','candidate':'mage'})
        while not game.done:
            available=[t for t in game.quest.plan['tasks'] if t['description']!='Обменять на побочную награду'
                       and _legal(t,frozenset(game.quest.completed),frozenset(game.quest.inventory))]
            self.assertTrue(available)
            task=available[0];travel(game.task_rooms[task['id']])
            if task['id']==game.quest.plan['goal']:
                do({'type':'unlock','code':'-'.join(game.code)})
                if game.battle:
                    solution=shortest_victory(game.battle)
                    self.assertEqual(solution['status'],'solved')
                    for attack in solution['actions']:do(attack)
            do({'type':'perform','target':task['id']})
        return game,actions,points

    def test_victory_100_monotonic_off_and_on(self):
        for combat in ('off','hard'):
            with self.subTest(combat=combat):
                game,actions,points=self._play(combat)
                self.assertEqual(game.terminal_reason,'completed')
                out=score(game,actions)
                self.assertEqual(out['score'],100.0);self.assertTrue(out['win'])
                self.assertTrue(all(a<=b for a,b in zip(points,points[1:])))
                part=out['components']['combat']
                if combat=='off':self.assertEqual(part['status'],'not_applicable');self.assertIsNone(part['fraction'])
                else:self.assertEqual(part['status'],'completed');self.assertEqual(part['fraction'],1.0)
                self.assertAlmostEqual(sum(x['weight'] for x in out['components'].values() if x['weight'] is not None),100,places=4)

    def test_unknown_nonterminal_and_replay_integrity(self):
        game=Game('score-incomplete',combat='off');out=score(game,[])
        self.assertIsNone(out['score']);self.assertFalse(out['complete_episode']);self.assertIsNone(out['win'])
        self.assertEqual(out['components']['code']['status'],'not_attempted')
        game.step({'type':'talk'})
        with self.assertRaises(ValueError):score(game,[])
        with self.assertRaises(ValueError):score(game,[{'type':'move','direction':'north'}])

    def test_prebrief_and_nonmandatory_visits_do_not_inflate_navigation(self):
        game=Game('score-wandering',combat='off',quests='hard');actions=[]
        # Visit all locations before the quest is revealed; visits alone do not score.
        for target in game.names:
            for d in shortest_directions(game.edges,game.position,target):
                a={'type':'move','direction':d};game.step(a);actions.append(a)
        out=score(game,actions)
        self.assertEqual(out['components']['objective_locations']['count'],0)
        self.assertEqual(out['components']['mandatory_quests']['count'],0)
        self.assertEqual(out['provisional_score'],0)

    def test_terminal_incorrect_code_and_missing_combat_are_distinct(self):
        # Solve the prerequisites, then use the wrong code.
        game=Game('score-badcode',combat='hard',party=True,quests='medium');actions=[]
        def do(a):game.step(a);actions.append(a)
        do({'type':'talk'})
        while not game._goal_ready():
            task=next(t for t in game.quest.plan['tasks'] if t['description']!='Обменять на побочную награду'
                      and t['id']!=game.quest.plan['goal'] and _legal(t,frozenset(game.quest.completed),frozenset(game.quest.inventory)))
            for d in shortest_directions(game.edges,game.position,game.task_rooms[task['id']]):do({'type':'move','direction':d})
            do({'type':'perform','target':task['id']})
        for d in shortest_directions(game.edges,game.position,game.goal_room):do({'type':'move','direction':d})
        do({'type':'unlock','code':'not-correct'})
        out=score(game,actions)
        self.assertEqual(out['terminal_reason'],'incorrect_code');self.assertFalse(out['win'])
        self.assertLess(out['score'],100);self.assertEqual(out['components']['code']['status'],'failed')
        self.assertEqual(out['components']['combat']['status'],'not_attempted')
        self.assertEqual(out['components']['combat']['fraction'],0)

    def test_combat_partial_progress_and_death_are_not_full_credit(self):
        game=Game('score-battle',combat='hard',party=False,quests='medium');actions=[]
        def do(a):game.step(a);actions.append(a)
        do({'type':'talk'})
        while not game._goal_ready():
            task=next(t for t in game.quest.plan['tasks'] if t['description']!='Обменять на побочную награду'
                      and t['id']!=game.quest.plan['goal'] and _legal(t,frozenset(game.quest.completed),frozenset(game.quest.inventory)))
            for d in shortest_directions(game.edges,game.position,game.task_rooms[task['id']]):do({'type':'move','direction':d})
            do({'type':'perform','target':task['id']})
        for d in shortest_directions(game.edges,game.position,game.goal_room):do({'type':'move','direction':d})
        do({'type':'unlock','code':'-'.join(game.code)})
        self.assertEqual(score(game,actions)['components']['combat']['status'],'in_progress')
        target=game.battle.enemies[0]['id']
        do({'type':'strike','actor':'hero','target':target})
        partial=score(game,actions)['components']['combat']
        self.assertGreater(partial['fraction'],0);self.assertLess(partial['fraction'],1)
        while not game.done:do({'type':'invalid'})
        out=score(game,actions)
        self.assertIn(out['terminal_reason'],('death','combat_limit'))
        self.assertEqual(out['components']['combat']['status'],'failed')
        self.assertGreater(out['components']['combat']['fraction'],0)
        self.assertLess(out['score'],100);self.assertFalse(out['win'])

    def test_optional_trade_cannot_earn_points_and_dead_end_is_partial(self):
        game=Game('score-trade',combat='off',quests='hard');actions=[]
        def do(action):game.step(action);actions.append(action)
        do({'type':'talk'})
        decoy=next(t for t in game.quest.plan['tasks'] if t['description']=='Обменять на побочную награду')
        while not _legal(decoy,frozenset(game.quest.completed),frozenset(game.quest.inventory)):
            tasks=[t for t in game.quest.plan['tasks'] if t['description']!='Обменять на побочную награду'
                   and t['id']!=game.quest.plan['goal'] and _legal(t,frozenset(game.quest.completed),frozenset(game.quest.inventory))]
            self.assertTrue(tasks)
            chosen=tasks[0]
            for direction in shortest_directions(game.edges,game.position,game.task_rooms[chosen['id']]):do({'type':'move','direction':direction})
            do({'type':'perform','target':chosen['id']})
            self.assertFalse(game.done)
        for direction in shortest_directions(game.edges,game.position,game.task_rooms[decoy['id']]):do({'type':'move','direction':direction})
        before=score(game,actions)
        do({'type':'perform','target':decoy['id']})
        after=score(game,actions)
        self.assertEqual(after['terminal_reason'],'dead_end')
        self.assertFalse(after['win'])
        self.assertEqual(before['provisional_score'],after['score'])
        self.assertLess(after['score'],100)
        self.assertEqual(before['components']['mandatory_quests']['count'],after['components']['mandatory_quests']['count'])

    def test_repeated_visits_and_invalid_actions_add_no_credit(self):
        game=Game('score-repeats',combat='off');actions=[]
        game.step({'type':'talk'});actions.append({'type':'talk'})
        before=score(game,actions)
        for _ in range(3):
            game.step({'type':'invalid'});actions.append({'type':'invalid'})
        after=score(game,actions)
        self.assertEqual(before['provisional_score'],after['provisional_score'])
        self.assertEqual(before['components'],after['components'])

if __name__=='__main__':unittest.main()
