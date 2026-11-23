import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmark import calibration as cal
from benchmark.memory_experiment import MAX_MEMORY_CHARS, MemoryClient, run, visible_memory


def user(zone, room, exits, message='', npc=None):
    return {'role': 'user', 'content': json.dumps({'zone': zone, 'room': room, 'exits': exits,
                                                  'message': message, 'npc': npc})}


def action(**content):
    return {'role': 'assistant', 'content': json.dumps(content)}


class VisibleMemoryTests(unittest.TestCase):
    def test_only_successful_visible_moves_and_observed_notes(self):
        history = [user('z', 'a', ['east'], 'start', 'npc'), action(type='ask', topic='x'),
                   user('z', 'a', ['east'], 'public clue', 'npc'),
                   action(type='move', direction='east'), user('z', 'b', ['west'], 'moved'),
                   action(type='move', direction='north'), user('z', 'b', ['west'], 'cannot move')]
        result = visible_memory(history)
        self.assertEqual(result['connections'], [{'from': 'z / a', 'direction': 'east', 'to': 'z / b'}])
        self.assertEqual(result['notes'], [{'location': 'z / a', 'after': 'ask', 'message': 'public clue', 'topic': 'x'}])
        self.assertNotIn('cannot move', json.dumps(result))
        self.assertNotIn('secret', json.dumps(result))

    def test_memory_is_bounded_and_reports_omissions(self):
        history = [user('z', 'a', ['east'])]
        for i in range(70):
            history += [action(type='ask', topic='x'), user('z', 'a', ['east'], str(i) + 'x' * 1800)]
        result = visible_memory(history)
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False, sort_keys=True)), MAX_MEMORY_CHARS)
        self.assertGreater(result['omitted_notes'], 0)

    def test_repeated_note_retains_latest_observation_at_capacity(self):
        def observed(turn, message):
            return {'role': 'user', 'content': json.dumps({'zone': 'z', 'room': 'a', 'exits': ['east'],
                                                          'turn': turn, 'message': message})}
        history = [observed(0, 'start')]
        for i in range(41):
            history += [action(type='ask', topic='clue'), observed(i + 1, f'note-{i}')]
        history += [action(type='ask', topic='clue'), observed(42, 'note-0')]
        result = visible_memory(history)
        self.assertEqual(len(result['notes']), 40)
        self.assertEqual(result['omitted_notes'], 1)
        self.assertEqual(result['notes'][-1], {'location': 'z / a', 'after': 'ask',
                                                'message': 'note-0', 'topic': 'clue', 'observed_turn': 42})
        self.assertNotIn('note-1', [n['message'] for n in result['notes']])
        self.assertEqual(result, visible_memory(history))

    def test_same_message_for_different_visible_topics_remains_distinct(self):
        history = [user('z', 'a', ['east']), action(type='ask', topic='one'),
                   user('z', 'a', ['east'], 'same'), action(type='ask', topic='two'),
                   user('z', 'a', ['east'], 'same')]
        self.assertEqual([n['topic'] for n in visible_memory(history)['notes']], ['one', 'two'])

    def test_context_window_preserved_and_old_observation_becomes_memory(self):
        client = MemoryClient('test', 'https://example.com/chat', 'x', context_turns=2)
        history = [user('z', 'a', ['east'], 'start', 'npc'), action(type='talk'),
                   user('z', 'a', ['east'], 'important clue', 'npc'), action(type='move', direction='east'),
                   user('z', 'b', ['west'], 'moved')]
        messages = client._messages(history)
        self.assertEqual(len(messages), 4)  # system plus current and one previous turn
        self.assertEqual(messages[1:3], history[-3:-1])
        latest = json.loads(messages[-1]['content'])
        self.assertEqual(latest['visible_memory']['notes'][0]['message'], 'important clue')


class ExperimentIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.plan = {'models': ['mock'], 'seeds': ['not-a-secret-test-seed'], 'max_turns': 2,
                     'context_turns': 1, 'fixed_probe_difficulty': None}

    def run_mode(self, folder, mode, resume=False, summary_only=False):
        return run(self.plan, mode=mode, api_url='https://example.com/v1/chat/completions',
                   api_key='' if summary_only else 'dummy', output_dir=folder,
                   resume=resume, summary_only=summary_only)

    def test_modes_separated_and_completed_checkpoints_are_not_repeated(self):
        calls = []
        def fake(client, messages):
            calls.append(messages)
            return '{"type":"rest"}'
        control = Path(self.tmp.name) / 'control'
        memory = Path(self.tmp.name) / 'memory'
        with patch.object(cal._Client, '_complete', fake):
            control_result = self.run_mode(control, 'control')
            memory_result = self.run_mode(memory, 'memory')
            self.assertEqual(len(calls), 4)
            self.assertNotIn('visible_memory', json.loads(calls[0][-1]['content']))
            self.assertIn('visible_memory', json.loads(calls[2][-1]['content']))
            self.assertEqual(control_result['summary']['game_groups'][0]['terminal'], 1)
            self.assertEqual(memory_result['summary']['game_groups'][0]['terminal'], 1)
            self.run_mode(memory, 'memory', resume=True)
            self.run_mode(memory, 'memory', summary_only=True)
            self.assertEqual(len(calls), 4)
            with self.assertRaises(ValueError):
                self.run_mode(memory, 'control', resume=True)
        self.assertEqual(os.stat(memory / 'experiment.json').st_mode & 0o777, 0o600)
        c = next((control / 'games').glob('*.json')).name
        m = next((memory / 'games').glob('*.json')).name
        self.assertNotEqual(c, m)
        control_spec = json.loads((control / 'games' / c).read_text())['spec']
        memory_spec = json.loads((memory / 'games' / m).read_text())['spec']
        self.assertEqual(control_spec.pop('memory_mode'), 'control')
        self.assertEqual(memory_spec.pop('memory_mode'), 'memory')
        self.assertEqual(control_spec, memory_spec)
        self.assertEqual(len(memory_spec['memory_prompt_sha256']), 64)

    def test_resume_reconstructs_identical_memory_without_network(self):
        interrupted, resumed, uninterrupted = [], [], []
        def fail_after_one(client, messages):
            interrupted.append(messages)
            if len(interrupted) == 2:
                raise RuntimeError('simulated network error')
            return '{"type":"rest"}'
        def after_resume(client, messages):
            resumed.append(messages)
            return '{"type":"rest"}'
        def whole(client, messages):
            uninterrupted.append(messages)
            return '{"type":"rest"}'
        with patch.object(cal._Client, '_complete', fail_after_one):
            result = self.run_mode(Path(self.tmp.name)/'resume', 'memory')
            self.assertEqual(result['summary']['game_groups'][0]['technical_errors'], 1)
        with patch.object(cal._Client, '_complete', after_resume):
            self.run_mode(Path(self.tmp.name)/'resume', 'memory', resume=True)
        with patch.object(cal._Client, '_complete', whole):
            self.run_mode(Path(self.tmp.name)/'whole', 'memory')
        self.assertEqual(resumed[0], uninterrupted[1])


if __name__ == '__main__':
    unittest.main()
