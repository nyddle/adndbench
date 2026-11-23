"""Independent solution and invariants for the development-only ladder."""
from collections import Counter
import json
import os
import re
import subprocess
import sys
import unittest

from benchmark.fixed_probes_ladder import (
    LEVELS, VERSION, check_response, generate_suite, public_probe, source_fingerprint,
)


class LadderTests(unittest.TestCase):
    def test_public_payload_determinism_and_scoring(self):
        self.assertEqual(VERSION, 'fixed-probes-ladder-0.1.0')
        self.assertRegex(source_fingerprint(), r'^[0-9a-f]{64}$')
        secret = 'PRIVATE-TEST-671abc45'
        for level in LEVELS:
            suite = generate_suite(secret, level)
            self.assertEqual(suite, generate_suite(secret, level))
            self.assertEqual(len(suite), 8)
            self.assertEqual(len({p['id'] for p in suite}), 8)
            self.assertEqual(Counter(p['answer'] for p in suite[:4]),
                             Counter(north=1, east=1, south=1, west=1))
            for p in suite:
                public = public_probe(p)
                self.assertNotIn('answer', public)
                self.assertNotIn(secret, json.dumps(public, ensure_ascii=False))
                self.assertTrue(check_response(p, json.dumps({'id': p['id'], 'answer': p['answer']})))
                self.assertFalse(check_response(p, json.dumps({'id': p['id'], 'answer': p['answer'], 'extra': 1})))
        for bad in (True, None, [], {}):
            with self.assertRaises(ValueError):
                generate_suite(bad, 'standard')
        with self.assertRaises(ValueError):
            generate_suite('dev', 'unknown')

    def test_independent_walk_and_swap_oracles(self):
        dirs = ['north', 'east', 'south', 'west']
        vectors = [(0, 1), (1, 0), (0, -1), (-1, 0)]
        for level, (length, events, tracked_events) in LEVELS.items():
            for seed in range(25):
                suite = generate_suite(f'ladder-dev-{seed}', level)
                for p in suite[:4]:
                    c = p['context']
                    self.assertEqual(len(c['steps']), length)
                    h = dirs.index(c['initial_heading'])
                    x = y = 0
                    seen = set()
                    for step in c['steps']:
                        h = (h + {'forward': 0, 'left': -1, 'right': 1, 'back': 2}[step]) % 4
                        seen.add(h)
                        dx, dy = vectors[h]
                        x += dx
                        y += dy
                    actual = ('east' if x > 0 else 'west') if x and not y else (
                        ('north' if y > 0 else 'south') if y and not x else None)
                    self.assertEqual(len(seen), 4)
                    self.assertEqual(actual, p['answer'])
                for p in suite[4:]:
                    c = p['context']
                    by_person = {v['person']: v['item'] for v in c['initial_assignments']}
                    self.assertEqual(len(by_person), 8)
                    self.assertEqual(len(set(by_person.values())), 8)
                    item = re.search(r'находится (.+?) после', p['question']).group(1)
                    touches = 0
                    self.assertEqual(len(c['events']), events)
                    for event in c['events']:
                        a, b = event['people']
                        self.assertEqual(event['action'], 'swap')
                        self.assertNotEqual(a, b)
                        touches += item in (by_person[a], by_person[b])
                        by_person[a], by_person[b] = by_person[b], by_person[a]
                    self.assertEqual(touches, tracked_events)
                    self.assertEqual(by_person[p['answer']], item)

    def test_cross_process_hash_seed(self):
        code = ('import json; from benchmark.fixed_probes_ladder import generate_suite; '
                'print(json.dumps(generate_suite("dev-only", "long"),ensure_ascii=False,sort_keys=True))')
        outputs = [subprocess.check_output([sys.executable, '-c', code], env={**os.environ, 'PYTHONHASHSEED': value})
                   for value in ('1', '321')]
        self.assertEqual(outputs[0], outputs[1])


if __name__ == '__main__':
    unittest.main()
