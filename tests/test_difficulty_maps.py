"""Properties needed before a generated map can back partial-observation play."""
from collections import Counter, deque
import json
import os
import subprocess
import sys
import unittest

from benchmark.difficulty.maps import OPPOSITE, generate_map


class GeneratedMapTests(unittest.TestCase):
    def test_sizes_connectivity_and_sites_over_many_seeds(self):
        for seed in range(20):
            for size in (6, 8, 10):
                with self.subTest(seed=seed, size=size):
                    world = generate_map(seed, size)
                    rooms = world['rooms']
                    by_id = {room['id']: room for room in rooms}
                    self.assertEqual(len(rooms), size * size + 22)
                    self.assertEqual(len(by_id), len(rooms))
                    self.assertEqual(len({room['name'] for room in rooms}), len(rooms))
                    counts = Counter(room['zone'] for room in rooms)
                    self.assertEqual(counts, {'overworld': size * size, 'mountain': 9, 'tower': 4, 'dungeon': 9})
                    sites = world['sites']
                    self.assertEqual(len(sites), len(set(sites.values())))
                    self.assertTrue(set(sites.values()).issubset(by_id))
                    self.assertEqual(by_id[sites['elder']]['zone'], 'overworld')
                    self.assertEqual(by_id[sites['herbalist']]['zone'], 'overworld')
                    self.assertEqual(by_id[sites['wizard']]['zone'], 'tower')
                    self.assertEqual(by_id[sites['dragon']]['zone'], 'dungeon')
                    self.assertEqual(by_id[sites['herb']]['zone'], 'mountain')
                    seen = {sites['elder']}
                    queue = deque(seen)
                    while queue:
                        room_id = queue.popleft()
                        for direction, target in by_id[room_id]['exits'].items():
                            self.assertIn(direction, OPPOSITE)
                            self.assertIn(target, by_id)
                            self.assertEqual(by_id[target]['exits'][OPPOSITE[direction]], room_id)
                            if direction in ('up', 'down'):
                                self.assertNotEqual(by_id[room_id]['zone'], by_id[target]['zone'])
                            else:
                                self.assertEqual(by_id[room_id]['zone'], by_id[target]['zone'])
                            if target not in seen:
                                seen.add(target)
                                queue.append(target)
                    self.assertEqual(seen, set(by_id))

    def test_cardinal_directions_match_coordinates(self):
        directions = {'north': (0, -1), 'south': (0, 1), 'east': (1, 0), 'west': (-1, 0)}
        for room in generate_map('geometry', 10)['rooms']:
            zone, x, y = room['id'].rsplit('-', 2)
            for direction, target in room['exits'].items():
                if direction in directions:
                    target_zone, nx, ny = target.rsplit('-', 2)
                    dx, dy = directions[direction]
                    self.assertEqual((target_zone, int(nx), int(ny)), (zone, int(x) + dx, int(y) + dy))

    def test_same_seed_determinism_across_process_hash_seeds(self):
        code = ('import json; from benchmark.difficulty.maps import generate_map; '
                'print(json.dumps(generate_map("hello", 8), ensure_ascii=False, sort_keys=True))')
        result = []
        for hash_seed in ('1', '41320'):
            env = dict(os.environ, PYTHONHASHSEED=hash_seed)
            result.append(subprocess.check_output([sys.executable, '-c', code], env=env, text=True))
        self.assertEqual(result[0], result[1])
        self.assertEqual(generate_map(1), generate_map('1'))
        self.assertNotEqual(generate_map(1), generate_map(2))

    def test_terrain_and_topology_axes_keep_unrelated_parts_fixed(self):
        plain = generate_map(3, 6, topology='winding', terrain_diversity=1)
        varied = generate_map(3, 6, topology='winding', terrain_diversity=3)
        self.assertEqual(plain['sites'], varied['sites'])
        for room_a, room_b in zip(plain['rooms'], varied['rooms']):
            self.assertEqual({k: v for k, v in room_a.items() if k != 'terrain'},
                             {k: v for k, v in room_b.items() if k != 'terrain'})
        self.assertNotEqual([r['terrain'] for r in plain['rooms']], [r['terrain'] for r in varied['rooms']])
        opened = generate_map(3, 6, topology='open', terrain_diversity=1)
        self.assertEqual(plain['sites'], opened['sites'])
        self.assertEqual([(r['id'], r['name'], r['zone'], r['terrain']) for r in plain['rooms']],
                         [(r['id'], r['name'], r['zone'], r['terrain']) for r in opened['rooms']])
        self.assertGreater(sum(len(r['exits']) for r in opened['rooms']),
                           sum(len(r['exits']) for r in plain['rooms']))

    def test_site_locations_vary_across_seeds(self):
        sites = [generate_map(seed)['sites'] for seed in range(20)]
        for key in ('herbalist', 'wizard', 'dragon', 'herb', 'bandit', 'guard'):
            self.assertGreater(len({site[key] for site in sites}), 1, key)

    def test_invalid_parameters_fail_explicitly(self):
        for seed in (None, True, 1.2, [], {}):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                generate_map(seed)
        for size in (True, 0, 4, 7, 11, '6', None):
            with self.subTest(size=size), self.assertRaises(ValueError):
                generate_map(1, size)
        for topology in ('treeish', '', None, 1):
            with self.subTest(topology=topology), self.assertRaises(ValueError):
                generate_map(1, topology=topology)
        for diversity in (True, 0, 4, '2', None):
            with self.subTest(diversity=diversity), self.assertRaises(ValueError):
                generate_map(1, terrain_diversity=diversity)


if __name__ == '__main__':
    unittest.main()
