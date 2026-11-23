"""Property tests for independently generated challenge probes."""
import heapq
import json
import re
import unittest
from collections import Counter

from benchmark.fixed_probes import FIXED_PROBES_V3, check_response, generate_suite_v3, public_probe


def route_oracle(probe):
    graph = {room['room']: room['exits'] for room in probe['context']['observed_map']}
    start, goal = re.findall(r'«([^»]+)»', probe['question'])
    distances, ways = {start: 0}, {start: 1}
    paths = {start: []}
    queue = [(0, start)]
    while queue:
        distance, room = heapq.heappop(queue)
        if distance != distances[room]:
            continue
        for direction, edge in graph[room].items():
            nxt, new = edge['room'], distance + edge['cost']
            if new < distances.get(nxt, float('inf')):
                distances[nxt], ways[nxt] = new, ways[room]
                paths[nxt] = paths[room] + [direction]
                heapq.heappush(queue, (new, nxt))
            elif new == distances.get(nxt):
                ways[nxt] += ways[room]
    return graph, ways[goal], paths[goal]


class ChallengeProbesTests(unittest.TestCase):
    def test_stable_version_public_payload_and_scoring(self):
        seed = 'development-seed-8ec661fc'
        probes = generate_suite_v3(seed)
        self.assertEqual(probes, generate_suite_v3(seed))
        self.assertEqual(FIXED_PROBES_V3, 'fixed-probes-0.3.0')
        self.assertEqual(len(probes), 12)
        self.assertEqual(len({p['id'] for p in probes}), 12)
        for probe in probes:
            public = public_probe(probe)
            self.assertNotIn('answer', public)
            self.assertNotIn(seed, json.dumps(public, ensure_ascii=False))
            self.assertTrue(check_response(probe, json.dumps({'id': probe['id'], 'answer': probe['answer']})))
        with self.assertRaises(ValueError):
            generate_suite_v3(True)

    def test_relative_walks_are_independent_and_correct(self):
        for seed in range(20):
            probes = generate_suite_v3(f'dev-{seed}')[:4]
            self.assertEqual(Counter(p['answer'] for p in probes), Counter(north=1, east=1, south=1, west=1))
            self.assertEqual(len({tuple(p['context']['steps']) for p in probes}), 4)
            for p in probes:
                context = p['context']
                self.assertTrue(8 <= len(context['steps']) <= 12)
                directions = ['north', 'east', 'south', 'west']
                delta = {'north': (0, 1), 'east': (1, 0), 'south': (0, -1), 'west': (-1, 0)}
                heading = directions.index(context['initial_heading'])
                x = y = 0
                seen = set()
                for step in context['steps']:
                    heading = (heading + {'forward': 0, 'left': -1, 'right': 1, 'back': 2}[step]) % 4
                    direction = directions[heading]
                    seen.add(direction)
                    dx, dy = delta[direction]
                    x += dx
                    y += dy
                self.assertEqual(seen, set(directions))
                expected = ('east' if x > 0 else 'west') if x and not y else (('north' if y > 0 else 'south') if y and not x else None)
                self.assertEqual(expected, p['answer'])

    def test_independent_routes_are_unique_and_long(self):
        opposite = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east'}
        for seed in range(20):
            probes = generate_suite_v3(f'dev-{seed}')[4:8]
            self.assertEqual(Counter(p['answer'] for p in probes), Counter(north=1, east=1, south=1, west=1))
            signatures = []
            ranks = []
            for p in probes:
                graph, ways, path = route_oracle(p)
                start = re.findall(r'«([^»]+)»', p['question'])[0]
                ranked = sorted(graph[start], key=lambda d: (graph[start][d]['cost'], d))
                self.assertEqual(len(ranked), 4)
                self.assertEqual(len({graph[start][d]['cost'] for d in ranked}), 4)
                ranks.append(ranked.index(p['answer']))
                self.assertEqual(len(graph), 49)
                self.assertGreater(sum(len(e) for e in graph.values()) // 2, len(graph) - 1)
                self.assertEqual(ways, 1)
                self.assertTrue(8 <= len(path) <= 12)
                self.assertEqual(path[0], p['answer'])
                signatures.append(tuple(sorted(edge['cost'] for exits in graph.values() for edge in exits.values())))
                for source, exits in graph.items():
                    for direction, edge in exits.items():
                        self.assertGreater(edge['cost'], 0)
                        self.assertEqual(graph[edge['room']][opposite[direction]], {'room': source, 'cost': edge['cost']})
            # Rotation preserves this weight multiset; differing signatures rule
            # out merely rotated copies for these development worlds.
            self.assertEqual(len(set(signatures)), 4)
            self.assertEqual(sorted(ranks), [0, 1, 2, 3])

    def test_quest_chains_and_independent_histories(self):
        for seed in range(20):
            probes = generate_suite_v3(f'dev-{seed}')[8:]
            histories = [json.dumps(p['context'], ensure_ascii=False, sort_keys=True) for p in probes]
            self.assertEqual(len(set(histories)), 4)
            for index, p in enumerate(probes):
                context = p['context']
                holdings = {x['person']: x['item'] for x in context['initial_assignments']}
                self.assertEqual(len(holdings), 8)
                self.assertEqual(len(set(holdings.values())), 8)
                tracked = p['answer'] if index % 2 else re.search(r'находится (.+?) после', p['question']).group(1)
                touched = 0
                self.assertEqual(len(context['events']), 12)
                for event in context['events']:
                    self.assertEqual(event['action'], 'swap')
                    a, b = event['people']
                    self.assertNotEqual(a, b)
                    touched += int(tracked in (holdings[a], holdings[b]))
                    holdings[a], holdings[b] = holdings[b], holdings[a]
                self.assertEqual(touched, 4)
                if index % 2:
                    person = re.search(r'персонажа (.+?) после', p['question']).group(1)
                    self.assertEqual(holdings[person], p['answer'])
                else:
                    self.assertEqual(holdings[p['answer']], tracked)


if __name__ == '__main__':
    unittest.main()
