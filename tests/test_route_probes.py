import json
import os
import subprocess
import sys
import unittest

from benchmark.route_probes import build_route_probes, public_probe, check_answer, _observed_graph


def walk(world, start, directions):
    """Build a runner-style trace from a fully reciprocal world map."""
    trace = []
    pos = start
    for direction in directions:
        nxt = world[pos][direction]
        trace.append({'observation': {'room': pos, 'exits': sorted(world[pos])},
                      'action': {'type': 'move', 'direction': direction}})
        pos = nxt
    return trace, {'room': pos, 'exits': sorted(world[pos])}


def bidirectional(links):
    world = {}
    opposite = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east',
                'up': 'down', 'down': 'up'}
    for room, direction, dest in links:
        world.setdefault(room, {})[direction] = dest
        world.setdefault(dest, {})[opposite[direction]] = room
    return world


class RouteProbesTest(unittest.TestCase):
    def test_unique_shortest_path_first_exit(self):
        world = bidirectional([
            ('A', 'north', 'B'), ('B', 'north', 'C'), ('C', 'north', 'D'),
            ('D', 'north', 'E'), ('C', 'east', 'F'),
        ])
        trace, final = walk(world, 'A', ['north', 'north', 'north', 'north',
                                         'south', 'south', 'east'])
        probes = build_route_probes(trace, final, min_distance=4)
        # Both directions of a distant pair are separate valid questions.
        self.assertEqual(len(probes), 2)
        probe = probes[0]
        self.assertEqual(probe['id'], 'route_planning_1')
        self.assertEqual(probe['capability'], 'route_planning')
        self.assertEqual(probe['answer'], 'north')
        self.assertIn('«A»', probe['question'])
        self.assertIn('«E»', probe['question'])
        self.assertNotIn('north «', probe['question'])
        self.assertEqual(probes[1]['answer'], 'south')
        self.assertTrue(check_answer(probe, ' North '))
        self.assertFalse(check_answer(probe, 'south'))
        self.assertEqual(set(public_probe(probe)), {'id', 'question'})

    def test_tied_paths_are_excluded(self):
        world = bidirectional([
            ('A', 'north', 'B'), ('A', 'east', 'C'),
            ('B', 'east', 'D'), ('C', 'north', 'D'),
        ])
        trace, final = walk(world, 'A', ['north', 'east', 'south', 'west'])
        self.assertEqual(build_route_probes(trace, final, min_distance=2), [])

    def test_min_distance_and_max_probes(self):
        rooms = [f'L{i}' for i in range(7)]
        world = bidirectional([(rooms[i], 'north', rooms[i + 1]) for i in range(6)])
        trace, final = walk(world, rooms[0], ['north'] * 6)
        # Pairs at distance >= 5, one probe per start room: L0→L5, L1→L6, L5→L0.
        probes = build_route_probes(trace, final, min_distance=5)
        self.assertEqual(len(probes), 3)
        self.assertEqual([p['answer'] for p in probes], ['north', 'north', 'south'])
        # Distance >= 6: L0→L6 and the reverse pair L6→L0.
        self.assertEqual(len(build_route_probes(trace, final, min_distance=6)), 2)
        self.assertEqual(len(build_route_probes(trace, final, min_distance=5, max_probes=1)), 1)
        self.assertEqual(build_route_probes(trace, final, min_distance=5, max_probes=0), [])

    def test_vertical_transitions(self):
        world = bidirectional([('A', 'up', 'B'), ('B', 'north', 'C')])
        trace, final = walk(world, 'A', ['up', 'north'])
        probes = build_route_probes(trace, final, min_distance=2)
        self.assertEqual(len(probes), 2)
        self.assertEqual(probes[0]['answer'], 'up')
        self.assertEqual(probes[1]['answer'], 'south')

    def test_reverse_edge_requires_observed_exit(self):
        # The destination observation hides the way back: no reverse edge.
        trace = [{'observation': {'room': 'A', 'exits': ['north']},
                  'action': {'type': 'move', 'direction': 'north'}},
                 {'observation': {'room': 'B', 'exits': ['east']},
                  'action': {'type': 'move', 'direction': 'east'}}]
        final = {'room': 'C', 'exits': []}
        edges, order = _observed_graph(trace, final)
        self.assertEqual(edges['A'], {'north': 'B'})
        self.assertEqual(edges['B'], {'east': 'C'})
        self.assertEqual(edges['C'], {})
        # With the way back visible, the reverse edge appears.
        trace[1]['observation']['exits'] = ['east', 'south']
        edges, _ = _observed_graph(trace, final)
        self.assertEqual(edges['B']['south'], 'A')

    def test_invalid_and_unmoved_actions_are_ignored(self):
        trace = [
            {'observation': {'room': 'A', 'exits': ['north']},
             'action': {'type': 'move', 'direction': 'south'}},   # not in exits
            {'observation': {'room': 'A', 'exits': ['north']},
             'action': {'type': 'search'}},                        # not a move
            {'observation': {'room': 'A', 'exits': ['north']},
             'action': {'type': 'move', 'direction': 'north'}},   # room unchanged below
        ]
        final = {'room': 'A', 'exits': ['north']}
        self.assertEqual(_observed_graph(trace, final), ({}, []))
        self.assertEqual(build_route_probes(trace, final), [])
        self.assertEqual(build_route_probes([{'observation': None, 'action': None}], final), [])

    def test_min_exits_filter(self):
        rooms = [f'L{i}' for i in range(7)]
        world = bidirectional([(rooms[i], 'north', rooms[i + 1]) for i in range(6)] +
                              [('L0', 'east', 'L2'), ('L0', 'west', 'L4')])
        trace, final = walk(world, 'L0', ['north', 'north', 'south', 'south',
                                          'east', 'north', 'north', 'south',
                                          'south', 'west', 'west'])
        # Only L0 has three observed exits; corridor rooms have two.
        probes = build_route_probes(trace, final, min_distance=4, min_exits=3)
        self.assertTrue(all(p['question'].split('«')[1].startswith('L0') for p in probes))
        self.assertEqual(build_route_probes(trace, final, min_distance=4, min_exits=4), [])
        with self.assertRaises(ValueError):
            build_route_probes(trace, final, min_exits=0)

    def test_validation_and_reproducibility(self):
        world = bidirectional([(f'R{i}', 'north', f'R{i + 1}') for i in range(6)])
        trace, final = walk(world, 'R0', ['north'] * 6)
        self.assertEqual(build_route_probes(trace, final), build_route_probes(trace, final))
        for kwargs in [{'min_distance': 1}, {'min_distance': 2.5}, {'min_distance': True},
                       {'max_probes': -1}]:
            with self.assertRaises(ValueError):
                build_route_probes(trace, final, **kwargs)
        code = ("import json; from tests.test_route_probes import walk, bidirectional; "
                "from benchmark.route_probes import build_route_probes; "
                "w = bidirectional([(f'R{i}', 'north', f'R{i + 1}') for i in range(6)]); "
                "t, f = walk(w, 'R0', ['north'] * 6); "
                "print(json.dumps(build_route_probes(t, f), sort_keys=True, ensure_ascii=False))")
        results = [subprocess.check_output([sys.executable, '-c', code],
                                           env={**os.environ, 'PYTHONHASHSEED': seed})
                   for seed in ('1', '22')]
        self.assertEqual(results[0], results[1])


if __name__ == '__main__':
    unittest.main()
