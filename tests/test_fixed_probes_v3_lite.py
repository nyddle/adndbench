"""Independent-oracle and shortcut tests for the separate v3-lite protocol."""
from collections import Counter, deque
import heapq
import json
import os
import re
import subprocess
import sys
import unittest

from benchmark.fixed_probes_v3_lite import (
    FIXED_PROBES_V3_LITE, check_response, generate_suite_v3_lite, public_probe, source_fingerprint,
)


def route_oracle(probe):
    graph = {r['room']: r['exits'] for r in probe['context']['observed_map']}
    start, goal = re.findall(r'«([^»]+)»', probe['question'])
    costs, ways, paths = {start: 0}, {start: 1}, {start: []}
    queue = [(0, start)]
    while queue:
        cost, current = heapq.heappop(queue)
        if cost != costs[current]:
            continue
        for direction, edge in graph[current].items():
            nxt, value = edge['room'], cost + edge['cost']
            if value < costs.get(nxt, float('inf')):
                costs[nxt], ways[nxt], paths[nxt] = value, ways[current], paths[current] + [direction]
                heapq.heappush(queue, (value, nxt))
            elif value == costs[nxt]:
                ways[nxt] += ways[current]
    # Independently find shortest-hop path first steps by running BFS from each
    # neighbor, rather than using the generator's propagation algorithm.
    bfs = {goal: 0}
    pending = deque([goal])
    while pending:
        room = pending.popleft()
        for edge in graph[room].values():
            if edge['room'] not in bfs:
                bfs[edge['room']] = bfs[room] + 1
                pending.append(edge['room'])
    first_steps = {d for d, e in graph[start].items() if bfs[e['room']] == bfs[start] - 1}
    return graph, start, goal, ways[goal], paths[goal], bfs[start], first_steps


class V3LiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.suites = [generate_suite_v3_lite(f'lite-dev-{i}') for i in range(20)]

    def test_version_schema_secrecy_scoring_and_independence(self):
        self.assertEqual(FIXED_PROBES_V3_LITE, 'fixed-probes-0.3-lite.2')
        self.assertRegex(source_fingerprint(), r'^[0-9a-f]{64}$')
        seed = 'PRIVATE-TEST-VALUE-9bac42'
        suite = generate_suite_v3_lite(seed)
        self.assertEqual(suite, generate_suite_v3_lite(seed))
        self.assertEqual(len(suite), 12)
        self.assertEqual(len({p['id'] for p in suite}), 12)
        self.assertEqual(len({json.dumps(p['context'], sort_keys=True, ensure_ascii=False) for p in suite}), 12)
        for p in suite:
            self.assertEqual(p['difficulty'], 'challenge-lite')
            public = public_probe(p)
            self.assertNotIn('answer', public)
            self.assertNotIn(seed, json.dumps(public, ensure_ascii=False))
            self.assertTrue(check_response(p, json.dumps({'id': p['id'], 'answer': p['answer']})))
            self.assertFalse(check_response(p, json.dumps({'id': p['id'], 'answer': p['answer'], 'extra': True})))
        for bad in (True, None, [], {}):
            with self.assertRaises(ValueError):
                generate_suite_v3_lite(bad)

    def test_walks_independently_match_direction_and_weak_shortcuts(self):
        directions = ['north', 'east', 'south', 'west']
        vectors = [(0, 1), (1, 0), (0, -1), (-1, 0)]
        initial_hits = final_hits = 0
        for suite in self.suites:
            self.assertEqual(Counter(p['answer'] for p in suite[:4]), Counter(directions))
            for p in suite[:4]:
                ctx = p['context']; heading = directions.index(ctx['initial_heading']); x = y = 0
                self.assertTrue(8 <= len(ctx['steps']) <= 12)
                seen = set()
                for turn in ctx['steps']:
                    heading = (heading + {'forward': 0, 'left': -1, 'right': 1, 'back': 2}[turn]) % 4
                    seen.add(directions[heading]); dx, dy = vectors[heading]; x += dx; y += dy
                self.assertEqual(seen, set(directions))
                answer = ('east' if x > 0 else 'west') if x and not y else (('north' if y > 0 else 'south') if y and not x else None)
                self.assertEqual(p['answer'], answer)
                initial_hits += p['answer'] == ctx['initial_heading']
                final_hits += p['answer'] == directions[heading]
        # These are weak empirical checks, not proof that no shortcut exists.
        self.assertLess(initial_hits, len(self.suites) * 4 * 0.65)
        self.assertLess(final_hits, len(self.suites) * 4 * 0.65)

    def test_routes_balanced_unique_cyclic_and_nontrivial_weights(self):
        opposite = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east'}
        sizes = set()
        for suite in self.suites:
            probes = suite[4:8]
            self.assertEqual(Counter(p['answer'] for p in probes), Counter(north=1, east=1, south=1, west=1))
            ranks = []
            signatures = []
            for p in probes:
                graph, start, goal, ways, path, min_hops, unweighted_first = route_oracle(p)
                sizes.add(len(graph))
                self.assertIn(len(graph), (25, 36))
                self.assertGreater(sum(len(e) for e in graph.values()) // 2, len(graph) - 1)
                self.assertEqual(ways, 1)
                self.assertTrue(5 <= len(path) <= 8)
                self.assertEqual(path[0], p['answer'])
                self.assertLess(min_hops, len(path))
                self.assertNotIn(p['answer'], unweighted_first)
                self.assertEqual(len(graph[start]), 4)
                self.assertEqual(len({x['cost'] for x in graph[start].values()}), 4)
                ranks.append(sorted(graph[start], key=lambda d: graph[start][d]['cost']).index(p['answer']))
                signatures.append(tuple(sorted(e['cost'] for links in graph.values() for e in links.values())))
                for source, links in graph.items():
                    for direction, edge in links.items():
                        self.assertTrue(1 <= edge['cost'] <= 9)
                        self.assertEqual(graph[edge['room']][opposite[direction]], {'room': source, 'cost': edge['cost']})
            self.assertEqual(sorted(ranks), [0, 1, 2, 3])
            self.assertEqual(len(set(signatures)), 4)
        self.assertEqual(sizes, {25, 36})

    def test_swap_histories_independently_recomputed(self):
        for suite in self.suites:
            for i, probe in enumerate(suite[8:]):
                ctx = probe['context']; holdings = {x['person']: x['item'] for x in ctx['initial_assignments']}
                self.assertEqual(len(holdings), 8)
                self.assertEqual(len(set(holdings.values())), 8)
                tracked = probe['answer'] if i % 2 else re.search(r'находится (.+?) после', probe['question']).group(1)
                touched = 0
                self.assertEqual(len(ctx['events']), 12)
                for event in ctx['events']:
                    a,b = event['people']; self.assertNotEqual(a, b)
                    touched += int(tracked in (holdings[a], holdings[b]))
                    holdings[a], holdings[b] = holdings[b], holdings[a]
                self.assertEqual(touched, 4)
                if i % 2:
                    person = re.search(r'персонажа (.+?) после', probe['question']).group(1)
                    self.assertEqual(holdings[person], probe['answer'])
                else:
                    self.assertEqual(holdings[probe['answer']], tracked)

    def test_reproducible_across_process_hash_seeds(self):
        code = ('import json; from benchmark.fixed_probes_v3_lite import generate_suite_v3_lite; '
                'print(json.dumps(generate_suite_v3_lite("determinism"),ensure_ascii=False,sort_keys=True))')
        outputs = [subprocess.check_output([sys.executable, '-c', code], env={**os.environ, 'PYTHONHASHSEED': value})
                   for value in ('1', '321')]
        self.assertEqual(outputs[0], outputs[1])


if __name__ == '__main__':
    unittest.main()
