import copy
import unittest
from benchmark.party_combat import Party, Battle, shortest_victory
from benchmark.party_adventure import Game, ENCOUNTERS


def enemy(**kw):
    return {'id': 'foe', 'hp': 8, 'damage': 3, 'armor': 0, 'target_rule': 'hero', **kw}

class PartyCombatTests(unittest.TestCase):
    def test_recruitment_local_bounded_and_snapshot(self):
        p = Party(gold=1, max_allies=1)
        self.assertFalse(p.recruit('mage', present=['medic']))
        self.assertTrue(p.recruit('mage', present=['mage']))
        before = p.snapshot()
        self.assertFalse(p.recruit('medic', present=['medic']))
        self.assertEqual(before, p.snapshot())
        self.assertEqual(Party.from_snapshot(before).snapshot(), before)
        bad = copy.deepcopy(before); bad['members']['mage']['charges'] = -1
        with self.assertRaises(ValueError): Party.from_snapshot(bad)

    def test_battle_guard_invalidation_and_persistence(self):
        p = Party(); p.recruit('warden', present=['warden']); p.recruit('medic', present=['medic'])
        b = Battle(p, [enemy()])
        b.step({'type':'guard','actor':'warden','target':'hero'})
        self.assertEqual(p.members['hero']['hp'], 11)
        self.assertEqual(p.members['warden']['charges'], 1)
        b.step({'type':'heal','actor':'medic','target':'hero'})
        self.assertEqual(p.members['hero']['hp'], 9)
        self.assertEqual(p.members['medic']['charges'], 1)
        b.step({'type':'strike','actor':'hero','target':'missing'})
        self.assertFalse(b.events[-1]['valid']); self.assertEqual(p.members['hero']['hp'], 6)
        self.assertEqual(p.snapshot(), Party.from_snapshot(p.snapshot()).snapshot())

    def test_targets_are_announced_killed_enemy_does_not_attack(self):
        p = Party(); p.recruit('mage', present=['mage'])
        b = Battle(p, [enemy(hp=5, damage=4, armor=2)])
        self.assertEqual(b.observe()['intents'][0]['target'], 'hero')
        b.step({'type':'blast','actor':'mage','target':'foe'})
        self.assertEqual(b.status, 'victory'); self.assertEqual(p.members['hero']['hp'], 12)
        self.assertEqual(p.members['mage']['charges'], 1)
        with self.assertRaises(RuntimeError): b.step({})

    def test_guard_empowers_next_strike_and_is_consumed(self):
        p=Party(); p.recruit('warden',present=['warden'])
        b=Battle(p,[enemy(hp=12,damage=1,armor=1)])
        b.step({'type':'guard','actor':'warden','target':'hero'})
        self.assertTrue(b.observe()['braced'])
        b.step({'type':'strike','actor':'hero','target':'foe'})
        self.assertEqual(b.enemies[0]['hp'],7)
        self.assertFalse(b.observe()['braced'])

    def test_fixed_party_and_scouting(self):
        g=Game(combat_difficulty='hard',fixed_party=('mage','medic'))
        self.assertEqual(g.party.recruited,['mage','medic'])
        self.assertEqual(len(g.observe()['scouting']),2)
        for direction in ('north','north'): g.step({'type':'move','direction':direction})
        self.assertEqual(g.observe()['party']['candidates_here'],[])
        g.step({'type':'recruit','candidate':'warden'})
        self.assertFalse(g.events[-1]['valid'])
        with self.assertRaises(ValueError): Game(fixed_party=('mage','mage'))

    def test_two_targets_and_dead_target_is_skipped(self):
        p = Party(); p.recruit('mage', present=['mage'])
        b = Battle(p, [enemy(id='a',hp=6, damage=7,target_rule='weakest'),
                       enemy(id='b',hp=6, damage=7,target_rule='weakest')])
        self.assertEqual([i['target'] for i in b.observe()['intents']], ['mage','mage'])
        b.step({'type':'strike','actor':'hero','target':'a'})
        self.assertEqual(p.members['mage']['hp'],0)
        self.assertEqual(len(b.events[-1]['incoming']),1)
        self.assertEqual([i['target'] for i in b.observe()['intents']], ['hero','hero'])

    def test_oracle_replays_and_distinguishes_unsolvable_and_unknown(self):
        p=Party(); b=Battle(p, [enemy(hp=12, armor=2)], max_rounds=8)
        self.assertEqual(shortest_victory(b)['status'], 'unsolvable')
        self.assertEqual(shortest_victory(b, max_states=1)['status'], 'unknown')
        p=Party(); p.recruit('mage',present=['mage'])
        b=Battle(p,[enemy(hp=12,armor=2)],max_rounds=8)
        initial = b.observe(); result=shortest_victory(b)
        self.assertEqual(result['status'],'solved'); self.assertEqual(initial,b.observe())
        for action in result['actions']: b.step(action)
        self.assertEqual(b.status,'victory')

    def test_playable_adventure_recruit_fight_return_and_replay(self):
        game=Game(combat_difficulty='medium')
        actions=[{'type':'move','direction':'north'}, {'type':'move','direction':'west'},
                 {'type':'recruit','candidate':'mage'}, {'type':'move','direction':'east'},
                 {'type':'move','direction':'north'}, {'type':'move','direction':'north'},
                 {'type':'blast','actor':'mage','target':'raider'},
                 {'type':'strike','actor':'hero','target':'raider'}, {'type':'search'},
                 {'type':'move','direction':'south'}, {'type':'move','direction':'south'},
                 {'type':'move','direction':'south'}]
        trace = [game.observe()]
        for action in actions: trace.append(game.step(action))
        self.assertEqual(game.result()['terminal_reason'],'completed')
        self.assertEqual(game.result()['invalid_actions'],0)
        self.assertEqual(game.party.members['mage']['charges'],1)
        replay = Game(combat_difficulty='medium')
        self.assertEqual(trace[0], replay.observe())
        for expected, action in zip(trace[1:], actions): self.assertEqual(expected,replay.step(action))
        self.assertEqual(replay.result(), game.result())

    def test_separate_levels_and_encounter_oracle(self):
        for difficulty in ENCOUNTERS:
            p=Party(); p.recruit('mage', present=['mage']); p.recruit('medic', present=['medic'])
            r=shortest_victory(Battle(p, ENCOUNTERS[difficulty]))
            self.assertEqual(r['status'],'solved')

if __name__ == '__main__': unittest.main()
