from collections import deque
import unittest
from benchmark import adventure_vectors as base
from benchmark.adventure_party import Game
from benchmark.party_combat import shortest_victory


def path_avoiding(game, destination, avoid=None):
    todo=deque([(game.game.position,[])]);seen={game.game.position}
    while todo:
        room,path=todo.popleft()
        if room == destination:return path
        for d,nxt in game.game.edges[room].items():
            if nxt not in seen and nxt != avoid:
                seen.add(nxt);todo.append((nxt,path+[d]))
    raise ValueError('unreachable without lock')


def apply_with_record(game, actions, action):
    actions.append(action);game.step(action)


def travel(game, actions, dest, auto_battle=True):
    while game.game.position != dest and not game.done:
        if game.battle and game.battle.status == 'ongoing':
            if not auto_battle: return
            verdict=shortest_victory(game.battle)
            if verdict['status'] != 'solved': raise RuntimeError('test battle not solvable')
            for action in verdict['actions']: apply_with_record(game,actions,action)
        else:
            direction=base.shortest_directions(game.game.edges,game.game.position,dest)[0]
            apply_with_record(game,actions,{'type':'move','direction':direction})
    if auto_battle and game.battle and game.battle.status == 'ongoing':
        verdict=shortest_victory(game.battle)
        if verdict['status'] != 'solved': raise RuntimeError('test battle not solvable')
        for action in verdict['actions']: apply_with_record(game,actions,action)


class AdventurePartyTests(unittest.TestCase):
    def test_disabled_is_exactly_base_and_replays(self):
        for seed in range(10):
            original=base.Game(seed,memory='medium',navigation='hard',quests='medium')
            wrapped=Game(seed,memory='medium',navigation='hard',quests='medium',party_enabled=False,combat_enabled=False)
            self.assertEqual(original.observe(),wrapped.observe())
            for action in base.oracle(original):
                self.assertEqual(original.step(action),wrapped.step(action))
            self.assertEqual(original.result(),wrapped.result())

    def test_party_recruitment_combat_persistence_and_replay(self):
        game=Game(26,memory='hard',navigation='easy',quests='hard',combat_difficulty='medium')
        actions=[]
        apply_with_record(game,actions,{'type':'talk'})
        mage=next(p for p,roles in game.candidates.items() if 'mage' in roles)
        for d in path_avoiding(game,mage,game.game.lock):
            apply_with_record(game,actions,{'type':'move','direction':d})
        self.assertIn('mage', [candidate['id'] for candidate in game.observe()['party']['candidates_here']])
        apply_with_record(game,actions,{'type':'recruit','candidate':'mage'})
        self.assertEqual(game.party.gold,1)
        self.assertEqual(game.party.members['mage']['charges'],2)
        for task in game.game.tasks:
            pos=next(p for p,name in game.game.names.items() if name==task['room'])
            travel(game,actions,pos)
            apply_with_record(game,actions,{'type':'interact','target':task['id']})
        travel(game,actions,game.game.lock)
        self.assertTrue(game.encounter_won)
        self.assertGreater(game.battle.round,0)
        self.assertLess(game.party.members['mage']['charges'],2)
        self.assertLess(game.party.members['hero']['hp'],12)
        hp,charges=game.party.members['hero']['hp'],game.party.members['mage']['charges']
        apply_with_record(game,actions,{'type':'unlock','code':'-'.join(game.game.code)})
        travel(game,actions,game.game.home)
        self.assertEqual(game.game.terminal_reason,'completed')
        self.assertEqual((game.party.members['hero']['hp'],game.party.members['mage']['charges']),(hp,charges))
        self.assertEqual(game.turn,len(actions))
        clone=Game(26,memory='hard',navigation='easy',quests='hard',combat_difficulty='medium')
        for action in actions: clone.step(action)
        self.assertEqual(game.observe(),clone.observe())
        self.assertEqual(game.result(),clone.result())

    def test_death_and_no_false_success_or_unlock(self):
        game=Game(8,combat_difficulty='hard')
        actions=[]
        apply_with_record(game,actions,{'type':'talk'})
        travel(game,actions,game.game.lock,auto_battle=False)
        self.assertEqual(game.battle.status,'ongoing')
        # An unlock while fighting is an invalid combat action, not an escape.
        apply_with_record(game,actions,{'type':'unlock','code':'-'.join(game.game.code)})
        self.assertEqual(game.battle.round,1)
        self.assertFalse(game.game.unlocked)
        while not game.done:
            apply_with_record(game,actions,{'type':'invalid'})
        self.assertEqual(game.game.terminal_reason,'death')
        self.assertFalse(game.encounter_won)
        self.assertFalse(game.game.unlocked)
        self.assertNotEqual(game.result()['terminal_reason'],'completed')
        self.assertEqual(game.turn,len(actions))
        with self.assertRaises(RuntimeError): game.step({'type':'move','direction':'north'})

    def test_recruitment_requires_local_candidate_and_respects_limit(self):
        game=Game(2,combat_enabled=False,max_allies=1)
        game.step({'type':'recruit','candidate':'mage'})
        self.assertEqual(game.game.invalid_actions,1)
        self.assertEqual(game.party.gold,2)
        first=next(iter(game.candidates))
        for d in base.shortest_directions(game.game.edges,game.game.position,first):game.step({'type':'move','direction':d})
        role=game.candidates[first][0]
        game.step({'type':'recruit','candidate':role})
        self.assertEqual(game.party.recruited,[role])
        game.step({'type':'recruit','candidate':role})
        self.assertEqual(game.game.invalid_actions,2)
        self.assertEqual(game.party.gold,1)

    def test_candidates_reachable_without_battle_and_axis_isolation(self):
        for seed in range(200):
            easy=Game(seed,navigation='easy',memory='easy',quests='easy')
            hard=Game(seed,navigation='hard',memory='hard',quests='hard')
            self.assertEqual(easy.candidates,hard.candidates)
            self.assertEqual(sum(len(x) for x in hard.candidates.values()),3)
            self.assertEqual({r for roles in hard.candidates.values() for r in roles}, {'mage','medic','warden'})
            for pos in hard.candidates:
                path_avoiding(hard,pos,hard.game.lock)

    def test_turn_limit_inside_combat(self):
        game=Game(8,combat_difficulty='hard',max_turns=5)
        for d in base.shortest_directions(game.game.edges,game.game.position,game.game.lock):
            if game.done: break
            game.step({'type':'move','direction':d})
        while not game.done:game.step({'type':'invalid'})
        self.assertIn(game.game.terminal_reason,('turn_limit','death','combat_limit'))
        self.assertNotEqual(game.game.terminal_reason,'completed')
        self.assertFalse(game.encounter_won)

if __name__=='__main__':unittest.main()
