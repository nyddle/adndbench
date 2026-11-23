"""Tests for seeded combat placement, telegraphing and tactical choices."""
import json
import os
import subprocess
import sys
import unittest
from collections import deque
from copy import deepcopy

from benchmark.difficulty.combat import (
    COMBAT_RULES, ENEMIES, apply_hit, generate_encounters, incoming, intent,
)


def grid_world():
    rooms = []
    for y in range(6):
        for x in range(6):
            here = f"r{x}-{y}"
            exits = {}
            for direction, dx, dy in (("north", 0, -1), ("south", 0, 1),
                                      ("east", 1, 0), ("west", -1, 0)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < 6 and 0 <= ny < 6:
                    exits[direction] = f"r{nx}-{ny}"
            rooms.append({"id": here, "name": here, "zone": "overworld", "exits": exits})
    return {"rooms": rooms, "sites": {"elder": "r0-0", "wizard": "r5-0", "dragon": "r5-5", "herb": "r0-5"}}


def reachable(world, blocked):
    rooms = {room['id']: room for room in world['rooms']}
    queue = deque([world['sites']['elder']])
    seen = set(queue)
    while queue:
        current = queue.popleft()
        for room in rooms[current]['exits'].values():
            if room not in blocked and room not in seen:
                seen.add(room)
                queue.append(room)
    return seen


class EncounterPlacementTests(unittest.TestCase):
    def test_profiles_are_seeded_monotone_and_do_not_mutate_world(self):
        world = grid_world()
        original = deepcopy(world)
        easy = generate_encounters(42, world, 'easy')
        medium = generate_encounters(42, world, 'medium')
        hard = generate_encounters(42, world, 'hard')
        self.assertEqual(world, original)
        self.assertEqual((len(easy), len(medium), len(hard)), (3, 5, 7))
        self.assertTrue(easy.keys() <= medium.keys())
        self.assertTrue(medium.keys() <= hard.keys())
        for room in easy:
            self.assertEqual(easy[room]['kind'], medium[room]['kind'])
        for room in medium:
            self.assertEqual(medium[room]['kind'], hard[room]['kind'])
        self.assertEqual(hard, generate_encounters('42', world, 'hard'))
        self.assertNotEqual(hard, generate_encounters(43, world, 'hard'))
        self.assertEqual(hard[world['sites']['dragon']]['kind'], 'dragon')

    def test_protected_sites_stay_connected_when_extra_monsters_are_blocked(self):
        world = grid_world()
        reserved = {'r2-2'}
        for seed in range(30):
            with self.subTest(seed=seed):
                encounters = generate_encounters(seed, world, 'hard', reserved_room_ids=reserved)
                blocked = set(encounters) - {world['sites']['dragon']}
                self.assertFalse(blocked & (set(world['sites'].values()) | reserved))
                self.assertTrue((set(world['sites'].values()) | reserved) <= reachable(world, blocked))

    def test_available_space_is_reported_by_actual_result_count(self):
        world = grid_world()
        encounters = generate_encounters(1, world, extra_count=500)
        self.assertLess(len(encounters) - 1, 500)
        blocked = set(encounters) - {world['sites']['dragon']}
        self.assertTrue(set(world['sites'].values()) <= reachable(world, blocked))

    def test_fixed_count_profiles_keep_locations_but_change_tactics(self):
        world = grid_world()
        cases = {level: generate_encounters(10, world, level, extra_count=3)
                 for level in ('easy', 'medium', 'hard')}
        self.assertEqual([len(cases[level]) for level in cases], [4, 4, 4])
        self.assertEqual(set(cases['easy']), set(cases['medium']))
        self.assertEqual(set(cases['easy']), set(cases['hard']))
        for room in cases['easy']:
            kind = cases['easy'][room]['kind']
            self.assertEqual(kind, cases['medium'][room]['kind'])
            self.assertEqual(kind, cases['hard'][room]['kind'])
            for level in cases:
                self.assertEqual(cases[level][room]['difficulty'], level)
            damages = [incoming(kind, 0, difficulty=level) for level in cases]
            self.assertEqual(damages, sorted(set(damages)))

    def test_replay_is_independent_of_python_hash_seed(self):
        program = '''
import json
from benchmark.difficulty.combat import generate_encounters
rooms = [{'id': str(i), 'exits': {'east': str((i+1)%8), 'west': str((i-1)%8)}} for i in range(8)]
print(json.dumps(generate_encounters(8, {'rooms': rooms, 'sites': {'elder': '0', 'dragon': '4'}}, 'hard'), sort_keys=True))
'''
        a = subprocess.check_output([sys.executable, '-c', program], env=dict(os.environ, PYTHONHASHSEED='1'))
        b = subprocess.check_output([sys.executable, '-c', program], env=dict(os.environ, PYTHONHASHSEED='8675309'))
        self.assertEqual(a, b)

    def test_reject_bad_configuration_and_disconnected_protected_site(self):
        world = grid_world()
        with self.assertRaises(ValueError):
            generate_encounters(1, world, 'impossible')
        with self.assertRaises(ValueError):
            generate_encounters(1, world, extra_count=-1)
        with self.assertRaises(ValueError):
            generate_encounters(1, world, reserved_room_ids=['not-a-room'])
        broken = deepcopy(world)
        for room in broken['rooms']:
            room['exits'] = {}
        with self.assertRaises(ValueError):
            generate_encounters(1, broken)


class EnemyIntentTests(unittest.TestCase):
    def test_telegraphed_defence_matters_and_never_costs_hp_on_a_zero_attack(self):
        fire = intent('dragon', 0, ward=True)
        self.assertEqual(fire['name'], 'огненное дыхание')
        self.assertEqual((fire['damage'], fire['damage_if_defending']), (4, 1))
        self.assertEqual(incoming('dragon', 0), 6)
        self.assertEqual(incoming('dragon', 1), 2)
        self.assertEqual(incoming('wisp', 0, defending=True), 0)
        self.assertEqual((incoming('wisp', 1), incoming('wisp', 1, defending=True)), (5, 1))
        self.assertIn('намерение', COMBAT_RULES)

    def test_armour_changes_physical_and_fire_choices(self):
        first = intent('sentinel', 0)
        second = intent('sentinel', 1)
        self.assertEqual(first['physical_damage_cap'], 1)
        self.assertIsNone(second['physical_damage_cap'])
        self.assertEqual(apply_hit('sentinel', 0, 3), 1)
        self.assertEqual(apply_hit('sentinel', 0, 3, damage_type='fire'), 3)
        self.assertEqual(apply_hit('sentinel', 1, 3), 3)
        self.assertEqual((incoming('sentinel', 1), incoming('sentinel', 1, defending=True)), (4, 1))
        self.assertEqual(ENEMIES['dragon']['hp'], 16)

    def test_profiles_telegraph_matching_resistance_and_damage(self):
        expected_fire_caps = {'easy': None, 'medium': 2, 'hard': 1}
        for level, cap in expected_fire_caps.items():
            with self.subTest(level=level):
                guard = intent('sentinel', 0, difficulty=level)
                self.assertEqual(guard['fire_damage_cap'], cap)
                if cap is not None:
                    self.assertIn(f'огненный не более {cap}', guard['description'])
                self.assertEqual(apply_hit('sentinel', 0, 7, damage_type='fire', difficulty=level),
                                 7 if cap is None else cap)
                self.assertEqual(guard['damage'], incoming('sentinel', 0, difficulty=level))
                self.assertEqual(guard['damage_if_defending'], incoming('sentinel', 0, defending=True, difficulty=level))
                dragon = intent('dragon', 0, ward=True, difficulty=level)
                self.assertEqual(dragon['damage'], incoming('dragon', 0, ward=True, difficulty=level))
                self.assertEqual(dragon['damage'], 4 + ('easy', 'medium', 'hard').index(level))
                self.assertEqual(dragon['damage_if_defending'], 1)

    def test_input_validation(self):
        for fn in (lambda: intent('unknown', 0), lambda: intent('dragon', -1), lambda: intent('dragon', 0, difficulty='bad'),
                   lambda: apply_hit('dragon', 0, -1), lambda: apply_hit('dragon', 0, 2, damage_type='poison')):
            with self.assertRaises(ValueError):
                fn()


if __name__ == '__main__':
    unittest.main()
