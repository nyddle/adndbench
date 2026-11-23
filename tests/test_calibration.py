import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from benchmark.calibration import run_calibration, validate_plan

KEY = 'local-test-secret-very-long'
URL = 'https://api.example.test/v1/chat/completions'
SEEDS = ['private-seed-B78431', 'private-seed-A28572']


def plan(**overrides):
    return {'models': ['small', 'large'], 'seeds': SEEDS, 'repeats': 1,
            'max_turns': 1, 'base_config': {'enemy_count': 1},
            'variants': [{'name': 'baseline', 'changes': {}},
                         {'name': 'combat', 'changes': {'combat_difficulty': 'hard'}}],
            **overrides}


class MockResponse(io.BytesIO):
    def __init__(self, content):
        super().__init__(json.dumps({'choices': [{'message': {'content': content}}],
                                    'usage': {'total_tokens': 5}}).encode())
    def __enter__(self):
        return self
    def __exit__(self, *_):
        self.close()


class CalibrationTests(unittest.TestCase):
    def test_duplicate_action_keys_are_invalid(self):
        p = plan(models=['small'], seeds=[SEEDS[0]],
                 variants=[{'name': 'baseline', 'changes': {}}])
        with tempfile.TemporaryDirectory() as tmp, patch('urllib.request.urlopen',
                return_value=MockResponse('{"type":"search","type":"talk"}')):
            out = Path(tmp) / 'private'
            run_calibration(p, api_url=URL, api_key=KEY, output_dir=out)
            saved = json.loads(next((out / 'games').glob('*.json')).read_text())
            self.assertEqual(saved['trace'][0]['action'], {'type': 'invalid'})
            self.assertEqual(saved['result']['invalid_actions'], 1)

    def test_paired_runs_and_private_checkpoint(self):
        requests = []
        def urlopen(req, timeout):
            payload = json.loads(req.data)
            requests.append(payload)
            self.assertEqual(req.get_header('Authorization'), 'Bearer ' + KEY)
            for seed in SEEDS:
                self.assertNotIn(seed, json.dumps(payload))
            self.assertNotIn(KEY, json.dumps(payload))
            return MockResponse('{"type":"talk"}')
        with tempfile.TemporaryDirectory() as tmp, patch('urllib.request.urlopen', urlopen):
            out = Path(tmp) / 'private'
            summary = run_calibration(plan(), api_url=URL, api_key=KEY, output_dir=out)
            self.assertEqual(len(requests), 8)
            self.assertTrue(all(g['terminal'] == 2 and g['turn_limits'] == 2 for g in summary['game_groups']))
            self.assertTrue(all(p['paired_terminal'] == 2 and p['excluded_missing_pairs'] == 0 for p in summary['paired_with_control']))
            again = run_calibration(plan(), api_url=URL, api_key=KEY, output_dir=out, resume=True)
            self.assertEqual(len(requests), 8)
            self.assertEqual(summary, again)
            self.assertEqual(out.stat().st_mode & 0o077, 0)
            for item in out.rglob('*'):
                if item.is_file():
                    self.assertEqual(item.stat().st_mode & 0o077, 0)
                    self.assertNotIn(KEY, item.read_text())
            # Reading finished results does not require an API key.
            self.assertEqual(summary, run_calibration(plan(), api_url=URL, api_key='', output_dir=out, summary_only=True))

    def test_resumes_error_and_does_not_send_scratchpad(self):
        requests = []
        def first(req, timeout):
            payload = json.loads(req.data)
            requests.append(payload)
            if len(requests) == 2:
                raise urllib.error.HTTPError(URL, 503, 'bad', {}, io.BytesIO(KEY.encode()))
            return MockResponse('{"type":"talk", "notes":"scratchpad marker"}')
        p = plan(models=['small'], seeds=[SEEDS[0]], variants=[{'name': 'baseline', 'changes': {}}], max_turns=2)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'private'
            with patch('urllib.request.urlopen', first):
                summary = run_calibration(p, api_url=URL, api_key=KEY, output_dir=out)
            group = summary['game_groups'][0]
            self.assertEqual((group['terminal'], group['missing_or_technical'], group['technical_errors']), (0, 1, 1))
            checkpoint = next((out / 'games').glob('*.json'))
            saved = json.loads(checkpoint.read_text())
            self.assertEqual(len(saved['trace']), 1)
            self.assertEqual(saved['trace'][0]['action'], {'type': 'invalid'})
            self.assertNotIn(KEY, checkpoint.read_text())
            def second(req, timeout):
                payload = json.loads(req.data)
                requests.append(payload)
                self.assertNotIn('scratchpad marker', json.dumps(payload))
                self.assertEqual(json.loads(payload['messages'][-2]['content']), {'type': 'invalid'})
                return MockResponse('{"type":"talk"}')
            with patch('urllib.request.urlopen', second):
                summary = run_calibration(p, api_url=URL, api_key=KEY, output_dir=out, resume=True)
            saved = json.loads(checkpoint.read_text())
            self.assertEqual(len(saved['trace']), 2)
            self.assertEqual(saved['result']['invalid_actions'], 1)
            self.assertEqual(summary['game_groups'][0]['terminal'], 1)
            self.assertEqual(len(requests), 3)
            saved['trace'][0]['next_observation']['message'] = 'tampered'
            checkpoint.write_text(json.dumps(saved))
            with self.assertRaises(ValueError):
                run_calibration(p, api_url=URL, api_key=KEY, output_dir=out, resume=True)

    def test_fixed_probes_are_isolated_and_no_answer_key_is_sent(self):
        from benchmark.fixed_probes import generate_suite
        requests = []
        def urlopen(req, timeout):
            payload = json.loads(req.data)
            messages = payload['messages']
            requests.append(payload)
            self.assertNotIn(SEEDS[0], json.dumps(payload))
            if 'Answer the question' in messages[0]['content']:
                self.assertEqual(len(messages), 2)
                public = json.loads(messages[1]['content'])
                self.assertNotIn('answer', public)
                self.assertNotIn('seed', public)
                return MockResponse(json.dumps({'id': public['id'], 'answer': 'wrong'}))
            return MockResponse('{"type":"talk"}')
        p = plan(models=['small'], seeds=[SEEDS[0]], fixed_probe_difficulty='medium')
        with tempfile.TemporaryDirectory() as tmp, patch('urllib.request.urlopen', urlopen):
            summary = run_calibration(p, api_url=URL, api_key=KEY, output_dir=Path(tmp)/'private')
            self.assertEqual(len(requests), 2 + len(generate_suite(SEEDS[0], 'medium')))
            self.assertEqual(sum(x['completed'] for x in summary['fixed_probes']), 10)
            self.assertEqual(sum(x['missing_or_technical'] for x in summary['fixed_probes']), 0)
            self.assertTrue(all(x['seed_repeat_coverage'] == 1 for x in summary['fixed_probes']))

    def test_validation_rejects_confounding_and_unsafe_url(self):
        with self.assertRaises(ValueError):
            validate_plan(plan(variants=[{'name': 'x', 'changes': {}}, {'name': 'y', 'changes': {'map_size': 7, 'npc_difficulty': 'hard'}}]))
        with self.assertRaises(ValueError):
            validate_plan(plan(base_config={}))
        with tempfile.TemporaryDirectory() as tmp:
            for url in ('http://remote.test/v1', 'https://user:pass@remote.test/v1', 'https://remote.test/v1?key=x'):
                with self.assertRaises(ValueError):
                    run_calibration(plan(), api_url=url, api_key=KEY, output_dir=Path(tmp)/'private')

    def test_missing_pair_is_not_treated_as_loss(self):
        def urlopen(req, timeout):
            data = json.loads(req.data)
            if data['model'] == 'bad':
                raise urllib.error.URLError('internal secret message')
            return MockResponse('{"type":"talk"}')
        p = plan(models=['bad'], seeds=[SEEDS[0]])
        with tempfile.TemporaryDirectory() as tmp, patch('urllib.request.urlopen', urlopen):
            result = run_calibration(p, api_url=URL, api_key=KEY, output_dir=Path(tmp)/'private')
            self.assertEqual(result['paired_with_control'][0]['paired_terminal'], 0)
            self.assertEqual(result['paired_with_control'][0]['excluded_missing_pairs'], 1)
            self.assertIsNone(result['game_groups'][0]['success_rate_terminal'])


if __name__ == '__main__':
    unittest.main()
