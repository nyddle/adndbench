"""Invariants for the opt-in fixed-probes v2 protocol."""
import heapq
import json
import re
import unittest
from collections import Counter, deque

from benchmark.fixed_probes import (
    FIXED_PROBES_V2, check_response, generate_suite, generate_suite_v2, public_probe,
)


def independent_routes(probe):
    graph = {room['room']: room['exits'] for room in probe['context']['observed_map']}
    start, end = re.findall(r'«([^»]+)»', probe['question'])
    distances = {start: 0}
    ways = {start: 1}
    firsts = {start: set()}
    queue = [(0, start)]
    while queue:
        dist, node = heapq.heappop(queue)
        if dist != distances[node]:
            continue
        for direction, edge in graph[node].items():
            to, cost = edge['room'], edge['cost']
            new = dist + cost
            first = {direction} if node == start else firsts[node]
            if new < distances.get(to, float('inf')):
                distances[to] = new
                ways[to] = ways[node]
                firsts[to] = set(first)
                heapq.heappush(queue, (new, to))
            elif new == distances.get(to):
                ways[to] += ways[node]
                firsts[to].update(first)
    # Independent unweighted BFS to detect a real distinction in task structure.
    hops = {start: 0}
    hop_firsts = {start: set()}
    bfs = deque([start])
    while bfs:
        node = bfs.popleft()
        for direction, edge in graph[node].items():
            to = edge['room']
            first = {direction} if node == start else hop_firsts[node]
            if to not in hops:
                hops[to] = hops[node] + 1
                hop_firsts[to] = set(first)
                bfs.append(to)
            elif hops[to] == hops[node] + 1:
                hop_firsts[to].update(first)
    return graph, ways[end], firsts[end], hop_firsts[end]


class FixedProbesV2Tests(unittest.TestCase):
    def test_reproducibility_version_and_v1_compatibility(self):
        self.assertEqual(FIXED_PROBES_V2, 'fixed-probes-0.2.0')
        for difficulty in ('medium', 'hard'):
            self.assertEqual(generate_suite_v2('development', difficulty),
                             generate_suite_v2('development', difficulty))
            self.assertEqual(len(generate_suite_v2('development', difficulty)), 10)
        old = generate_suite('development', 'medium')
        self.assertEqual(len(old), 10)
        self.assertTrue(all(not p['id'].startswith('v2_') for p in old))
        with self.assertRaises(ValueError):
            generate_suite_v2('development', 'easy')
        with self.assertRaises(ValueError):
            generate_suite_v2(True)

    def test_spatial_answers_and_balance(self):
        kinds = set()
        for difficulty in ('medium', 'hard'):
            for seed in range(40):
                suite = generate_suite_v2(seed, difficulty)
                displacement, routes = suite[:4], suite[4:8]
                route_answers = Counter(p['answer'] for p in routes)
                self.assertEqual(route_answers, Counter(north=1, east=1, south=1, west=1))
                for probe in displacement:
                    steps = Counter(probe['context']['movements'])
                    self.assertTrue(all(steps[d] > 0 for d in ('north', 'south', 'east', 'west')))
                    x, y = steps['east'] - steps['west'], steps['north'] - steps['south']
                    parts = [('north' if y > 0 else 'south') if y else '',
                             ('east' if x > 0 else 'west') if x else '']
                    expected = '-'.join(p for p in parts if p) or 'same'
                    self.assertEqual(probe['answer'], expected)
                    kinds.add('same' if not (x or y) else 'diagonal' if x and y else 'cardinal')
                answers = Counter(p['answer'] for p in displacement)
                if 'same' in answers:
                    self.assertEqual(answers, {'same': 4})
                else:
                    self.assertEqual(len(answers), 4)
        self.assertEqual(kinds, {'same', 'cardinal', 'diagonal'})

    def test_weighted_routes_are_cyclic_and_have_unique_correct_answer(self):
        weight_changes_first_move = False
        for difficulty in ('medium', 'hard'):
            for seed in range(25):
                for probe in generate_suite_v2(seed, difficulty)[4:8]:
                    graph, ways, firsts, hop_firsts = independent_routes(probe)
                    self.assertEqual(len(graph), 16 if difficulty == 'medium' else 25)
                    self.assertGreater(sum(len(exits) for exits in graph.values()) // 2, len(graph) - 1)
                    self.assertEqual(ways, 1)
                    self.assertEqual(firsts, {probe['answer']})
                    weight_changes_first_move |= probe['answer'] not in hop_firsts
                    for node, exits in graph.items():
                        for direction, edge in exits.items():
                            reverse = {'north':'south','south':'north','east':'west','west':'east'}[direction]
                            self.assertEqual(graph[edge['room']][reverse], {'room': node, 'cost': edge['cost']})
                            self.assertGreater(edge['cost'], 0)
        self.assertTrue(weight_changes_first_move)

    def test_quest_reference_and_updates_among_distractors(self):
        for difficulty in ('medium', 'hard'):
            for seed in range(25):
                assignment, update = generate_suite_v2(seed, difficulty)[8:]
                history = update['context']['history']
                name, item = re.search(r'для персонажа (.+?)\?', update['question']).group(1), re.search(r'найти (.+?) для персонажа', update['question']).group(1)
                relevant = [event for event in history if event.startswith('Изменение поручения: ' + name + ' сообщает, что ' + item + ' ')]
                self.assertEqual(len(relevant), 2)
                self.assertNotEqual(relevant[-1], history[-1])
                self.assertGreater(history.index(relevant[-1]) - history.index(relevant[0]), 1)
                self.assertNotEqual(re.findall(r'«([^»]+)»', relevant[0])[0], update['answer'])
                self.assertEqual(re.findall(r'«([^»]+)»', relevant[-1])[0], update['answer'])
                asked = re.search(r'найти (.+?)\?', assignment['question']).group(1)
                matching = [event for event in history if event.startswith(asked + ' просит найти ')]
                self.assertEqual(len(matching), 1)
                self.assertIn(assignment['answer'], matching[0])

    def test_public_payload_and_strict_scoring(self):
        secret_seed = 'v2-test-seed-d61fdcc71b57'
        for probe in generate_suite_v2(secret_seed):
            public = public_probe(probe)
            self.assertNotIn('answer', public)
            self.assertNotIn(secret_seed, json.dumps(public, ensure_ascii=False))
            response = json.dumps({'id': probe['id'], 'answer': probe['answer']}, ensure_ascii=False)
            self.assertTrue(check_response(probe, response))
            self.assertFalse(check_response(probe, json.dumps({'id': probe['id'], 'answer': probe['answer'], 'note': 'extra'})))


if __name__ == '__main__':
    unittest.main()
