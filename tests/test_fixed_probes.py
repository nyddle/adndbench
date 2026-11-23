"""Common-state tasks must be deterministic, answerable and safely disclosed."""
import json
import os
import re
import subprocess
import sys
import unittest
from collections import Counter, deque

from benchmark.fixed_probes import generate_suite, public_probe, check_response


class FixedProbeTests(unittest.TestCase):
    def test_replay_is_stable_across_processes_and_hash_seeds(self):
        code = ("import json; from benchmark.fixed_probes import generate_suite; "
                "print(json.dumps(generate_suite('sample', 'hard'),sort_keys=True,ensure_ascii=False))")
        results = [subprocess.check_output([sys.executable, '-c', code], text=True,
                   env={**os.environ, 'PYTHONHASHSEED': setting}) for setting in ('1', '99999')]
        self.assertEqual(results[0], results[1])
        self.assertEqual(generate_suite(17), generate_suite('17'))
        self.assertNotEqual(generate_suite(17), generate_suite(18))

    def test_public_probe_strips_private_key_and_copies_nested_context(self):
        for private in generate_suite('sample'):
            public = public_probe(private)
            self.assertNotIn('answer', public)
            self.assertNotIn('seed', public)
            self.assertNotIn('answer', public['context'])
            # An agent or adapter can never mutate the evaluator's private key.
            public['context']['modified'] = True
            self.assertNotIn('modified', private['context'])
            self.assertIsInstance(private['answer'], str)
            # Direction questions may enumerate all four response choices;
            # listing choices is not the same as exposing the correct one.
            if private['capability'] == 'quest_memory':
                self.assertNotIn(private['answer'].casefold(), private['question'].casefold())

    def test_direction_balance_and_displacements_from_visible_steps(self):
        vectors = {'north': (0, -1), 'east': (1, 0), 'south': (0, 1), 'west': (-1, 0)}
        for seed in range(100):
            for difficulty in ('easy', 'medium', 'hard'):
                suite = generate_suite(seed, difficulty)
                self.assertEqual(len({p['id'] for p in suite}), 10)
                displacements = [p for p in suite if p['id'].startswith('spatial_displacement_')]
                self.assertEqual(Counter(p['answer'] for p in displacements), Counter(vectors.keys()))
                for probe in displacements:
                    x = sum(vectors[d][0] for d in probe['context']['movements'])
                    y = sum(vectors[d][1] for d in probe['context']['movements'])
                    self.assertGreaterEqual(len(probe['context']['movements']), 3)
                    self.assertNotEqual(probe['context']['movements'][-1], probe['answer'])
                    self.assertTrue((x == 0) != (y == 0))
                    answer = ('east' if x > 0 else 'west') if x else ('south' if y > 0 else 'north')
                    self.assertEqual(probe['answer'], answer)

    def test_route_is_unique_nontrivial_and_solved_from_public_map(self):
        for seed in range(100):
            for difficulty in ('easy', 'medium', 'hard'):
                probes = [p for p in generate_suite(seed, difficulty) if p['id'].startswith('spatial_route_')]
                self.assertEqual(Counter(p['answer'] for p in probes), Counter(('north', 'east', 'south', 'west')))
                for probe in probes:
                    names = re.findall(r'«([^»]+)»', probe['question'])
                    self.assertEqual(len(names), 2)
                    start, target = names
                    graph = {r['room']: r['exits'] for r in probe['context']['observed_map']}
                    reverse = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east'}
                    for source, exits in graph.items():
                        for direction, destination in exits.items():
                            self.assertEqual(graph[destination].get(reverse[direction]), source)
                    self.assertGreaterEqual(len(graph[start]), 2)
                    self.assertNotIn(target, graph[start].values())
                    paths, queue = [], deque([(start, [])])
                    while queue:
                        here, path = queue.popleft()
                        if paths and len(path) > len(paths[0]):
                            continue
                        if here == target:
                            paths.append(path)
                            continue
                        for direction, nxt in graph[here].items():
                            if nxt not in [start] + [r for _, r in path]:
                                queue.append((nxt, path + [(direction, nxt)]))
                    self.assertEqual(len(paths), 1)
                    self.assertGreaterEqual(len(paths[0]), 2)
                    self.assertEqual(paths[0][0][0], probe['answer'])

    def test_quest_answers_follow_visible_assignment_and_latest_update(self):
        assignment_re = re.compile(r'^(.*?) просит найти (.*?) в месте «(.*?)»\.$')
        update_re = re.compile(r'^Изменение поручения: (.*?) сообщает, что (.*?) теперь находится в месте «(.*?)»')
        for seed in range(50):
            for difficulty in ('easy', 'medium', 'hard'):
                suite = {p['id']: p for p in generate_suite(seed, difficulty)}
                one, two = suite['quest_assignment'], suite['quest_update']
                history = one['context']['history']
                self.assertEqual(history, two['context']['history'])
                assignments = [assignment_re.match(event) for event in history[:-1]]
                self.assertTrue(all(assignments))
                people = {m.group(1): (m.group(2), m.group(3)) for m in assignments}
                giver = re.search(r'найти (.*?)\?', one['question']).group(1)
                self.assertEqual(one['answer'], people[giver][0])
                update = update_re.match(history[-1])
                self.assertIsNotNone(update)
                self.assertIn(update.group(1), people)
                self.assertIn(update.group(2), two['question'])
                self.assertNotEqual(update.group(3), people[update.group(1)][1])
                self.assertEqual(two['answer'], update.group(3))

    def test_strict_json_protocol_and_exact_scoring(self):
        probe = generate_suite('test')[0]
        self.assertTrue(check_response(probe, {'id': probe['id'], 'answer': '  ' + probe['answer'].upper() + '  '}))
        self.assertTrue(check_response(probe, json.dumps({'id': probe['id'], 'answer': probe['answer']})))
        self.assertFalse(check_response(probe, {'id': 'wrong', 'answer': probe['answer']}))
        self.assertFalse(check_response(probe, {'id': probe['id'], 'answer': probe['answer'] + 'x'}))
        self.assertFalse(check_response(probe, {'id': probe['id'], 'answer': probe['answer'], 'extra': True}))
        self.assertFalse(check_response(probe, 'not json'))
        self.assertFalse(check_response(probe, '{"id":"x","id":"y","answer":"north"}'))
        self.assertFalse(check_response(probe, ['not', 'object']))

    def test_invalid_inputs_are_rejected(self):
        for seed in (True, None, [], 1.5):
            with self.assertRaises(ValueError):
                generate_suite(seed)
        for difficulty in ('unknown', None, 1):
            with self.assertRaises(ValueError):
                generate_suite(1, difficulty)


if __name__ == '__main__':
    unittest.main()
