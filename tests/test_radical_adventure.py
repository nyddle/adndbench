import unittest
from benchmark import quest_trial
from benchmark.radical_adventure import Game,shortest_directions,source_fingerprint
from benchmark.party_combat import shortest_victory


def play_oracle(seed,**kwargs):
    game=Game(seed,**kwargs); actions=[]; observed=[]
    def do(a):
        observed.append(game.observe());actions.append(a);game.step(a)
    def travel(target):
        for d in shortest_directions(game.edges,game.position,target):do({'type':'move','direction':d})
    do({'type':'talk'})
    if game.combat=='hard' and game.party_enabled:
        mage=next(cell for cell,roles in game.candidates.items() if 'mage' in roles)
        travel(mage);do({'type':'recruit','candidate':'mage'})
    verdict=quest_trial.oracle(game.quest)
    if verdict['status']!='solved':raise AssertionError('quest solver did not solve')
    for action in verdict['actions']:
        target=action['target'];travel(game.task_rooms[target])
        if target==game.quest.plan['goal']:
            do({'type':'unlock','code':'-'.join(game.code)})
            if game.battle:
                fight=shortest_victory(game.battle)
                if fight['status']!='solved':raise AssertionError('combat solver did not solve')
                for attack in fight['actions']:do(attack)
        do(action)
    return game,actions,observed


class RadicalAdventureTests(unittest.TestCase):
    def test_full_adventure_solved_and_replayed(self):
        for combat in ('off','easy','medium','hard'):
            for seed in range(12):
                game,actions,observations=play_oracle(seed,combat=combat,memory='hard',quests='hard',navigation='hard')
                self.assertEqual(game.result()['terminal_reason'],'completed')
                self.assertEqual(game.invalid_actions,0)
                self.assertEqual(game.turn,len(actions))
                clone=Game(seed,combat=combat,memory='hard',quests='hard',navigation='hard')
                for action,expected in zip(actions,observations):
                    self.assertEqual(clone.observe(),expected);clone.step(action)
                self.assertEqual(game.observe(),clone.observe())
                self.assertEqual(game.result(),clone.result())

    def test_private_values_not_leaked_and_one_shot_clue(self):
        seed='SECRET-test-radical-9241'
        game=Game(seed,memory='extreme')
        self.assertNotIn(seed,repr(game.observe()))
        self.assertEqual(game.observe()['tasks'],[])
        first=game.step({'type':'talk'})
        self.assertEqual(len(first['notice']['runes']),4)
        game.step({'type':'talk'})
        self.assertNotIn('runes',game.observe()['notice'])
        self.assertNotIn('-'.join(game.code),repr(game.observe()))
        self.assertEqual(len(source_fingerprint()),64)

    def test_axes_do_not_change_other_subsystems(self):
        for seed in range(30):
            a=Game(seed,memory='easy',navigation='easy',quests='medium',combat='easy',party=True)
            b=Game(seed,memory='extreme',navigation='hard',quests='medium',combat='hard',party=True)
            self.assertEqual(a.names,b.names)
            self.assertEqual(a.task_rooms,b.task_rooms)
            self.assertEqual(a.candidates,b.candidates)
            self.assertEqual(a.quest.plan,b.quest.plan)
            self.assertEqual(a.code,b.code[:1])
            for room,exits in b.edges.items():
                self.assertTrue(set(exits.items())<=set(a.edges[room].items()))

    def test_wrong_code_and_invalid_move_are_distinct(self):
        g=Game('f',combat='off',quests='medium')
        g.step({'type':'talk'})
        solution=quest_trial.oracle(g.quest)['actions']
        for action in solution[:-1]:
            for d in shortest_directions(g.edges,g.position,g.task_rooms[action['target']]):g.step({'type':'move','direction':d})
            g.step(action)
        for d in shortest_directions(g.edges,g.position,g.goal_room):g.step({'type':'move','direction':d})
        self.assertTrue(g._goal_ready())
        g.step({'type':'unlock','code':'wrong'})
        self.assertTrue(g.done);self.assertEqual(g.terminal_reason,'incorrect_code')
        self.assertFalse(g.unlocked)

    def test_irrecoverable_trade_ends_early_without_false_completion(self):
        game=Game('trade-check',quests='hard',combat='off')
        game.step({'type':'talk'})
        decoy=next(t for t in game.quest.plan['tasks'] if t['description']=='Обменять на побочную награду')
        for action in quest_trial.oracle(game.quest)['actions']:
            if set(decoy['requires'])<=game.quest.completed and set(decoy['consumes'])<=game.quest.inventory:break
            for d in shortest_directions(game.edges,game.position,game.task_rooms[action['target']]):game.step({'type':'move','direction':d})
            game.step(action)
            self.assertFalse(game.done)
        else:self.fail('decoy did not become available')
        for d in shortest_directions(game.edges,game.position,game.task_rooms[decoy['id']]):game.step({'type':'move','direction':d})
        game.step({'type':'perform','target':decoy['id']})
        self.assertTrue(game.done)
        self.assertEqual(game.terminal_reason,'dead_end')
        self.assertEqual(quest_trial.oracle(game.quest)['status'],'unsolvable')

    def test_no_false_victory_on_invalid_battle(self):
        g=Game('battle',memory='easy',quests='medium',combat='hard',party=False)
        g.step({'type':'talk'})
        for action in quest_trial.oracle(g.quest)['actions'][:-1]:
            for d in shortest_directions(g.edges,g.position,g.task_rooms[action['target']]):g.step({'type':'move','direction':d})
            g.step(action)
        for d in shortest_directions(g.edges,g.position,g.goal_room):g.step({'type':'move','direction':d})
        g.step({'type':'unlock','code':'-'.join(g.code)})
        while not g.done:g.step({'type':'invalid'})
        self.assertIn(g.terminal_reason,('death','combat_limit'))
        self.assertNotEqual(g.terminal_reason,'completed')

if __name__=='__main__':unittest.main()
