"""Scenario configuration and disclosure through the public runner."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import types
import unittest
from unittest.mock import patch

from benchmark.runner import OpenAICompatibleAgent, main, run_episode


class _FakeGame:
    """Minimal public-game double to isolate the runner from world generation."""
    def __init__(self, seed, max_turns, **config):
        self.seed, self.max_turns = seed, max_turns
        self.config = dict(config)
        self.turn = 0

    def observe(self):
        return {'room': 'visible', 'exits': [], 'turn': self.turn, 'done': bool(self.turn)}

    def step(self, action):
        self.turn += 1
        return self.observe()

    def result(self):
        return {'seed': self.seed, 'turns': self.turn, 'invalid_actions': 0,
                'terminal_reason': 'turn_limit', 'events': [],
                'component_versions': {'map': 'test-map'}}


class _Agent:
    def __init__(self):
        self.observations = []

    def act(self, observation):
        self.observations.append(observation)
        return {'type': 'search'}

    def answer_probe(self, observation, question):
        raise AssertionError('no probe should be generated from this trajectory')


def _module():
    fake = types.ModuleType('benchmark.expedition')
    fake.Game = _FakeGame
    fake.DEFAULT_MAX_TURNS = 321
    fake.ENGINE_VERSION = 'test-expedition'
    fake.SYSTEM_PROMPT = 'test expedition public rules'
    return fake


class ExpeditionRunnerTests(unittest.TestCase):
    def test_programmatic_episode_applies_axes_and_handles_empty_probes(self):
        config = {'map_size': 8, 'map_topology': 'winding', 'terrain_diversity': 3,
                  'quest_difficulty': 'hard', 'combat_difficulty': 'easy',
                  'character_class': 'scout', 'npc_difficulty': 'medium', 'enemy_count': 2}
        agent = _Agent()
        with patch.dict(sys.modules, {'benchmark.expedition': _module()}):
            episode = run_episode(9, agent, scenario='expedition', scenario_config=config)
        self.assertEqual(episode['config'], config)
        self.assertEqual(episode['scenario'], 'expedition')
        self.assertEqual(agent.observations, [{'room': 'visible', 'exits': [], 'turn': 0, 'done': False}])
        self.assertEqual(episode['probes'], [])
        self.assertTrue(all(value is None for value in episode['score']['capability_scores'].values()))

    def test_expedition_probes_use_scenario_and_do_not_expose_answers(self):
        class Agent(_Agent):
            def __init__(self):
                super().__init__()
                self.questions = []
            def answer_probe(self, observation, question):
                self.questions.append(question)
                return 'Гора'
        agent = Agent()
        probe = {'id': 'q1', 'capability': 'quest_memory', 'question': 'Где?', 'answer': 'Гора'}
        with patch.dict(sys.modules, {'benchmark.expedition': _module()}), \
                patch('benchmark.runner.build_probes', return_value=[probe]) as build:
            episode = run_episode(9, agent, scenario='expedition')
        self.assertEqual(build.call_args.kwargs['scenario'], 'expedition')
        self.assertEqual(agent.questions, [{'id': 'q1', 'question': 'Где?'}])
        self.assertEqual(episode['score']['capability_scores']['quest_memory'], 1)

    def test_openai_agent_receives_correct_scenario_prompt(self):
        agent = OpenAICompatibleAgent('model', 'https://example.test', 'fake')
        seen = []
        def respond(messages):
            seen.append(messages)
            return '{"type":"search"}'
        agent._complete = respond
        with patch.dict(sys.modules, {'benchmark.expedition': _module()}):
            run_episode(1, agent, probes=False, scenario='expedition')
        self.assertEqual(seen[0][0]['content'], 'test expedition public rules')
        self.assertNotIn('seed', json.loads(seen[0][1]['content']))

    def test_custom_prompt_is_not_overwritten(self):
        agent = OpenAICompatibleAgent('model', 'https://example.test', 'fake', system_prompt='custom')
        seen = []
        agent._complete = lambda messages: (seen.append(messages) or '{"type":"search"}')
        with patch.dict(sys.modules, {'benchmark.expedition': _module()}):
            run_episode(1, agent, probes=False, scenario='expedition')
        self.assertEqual(seen[0][0]['content'], 'custom')

    def test_classic_rejects_inapplicable_axis_configuration(self):
        with self.assertRaisesRegex(ValueError, 'scenario_config'):
            run_episode(1, _Agent(), scenario='classic', scenario_config={'map_size': 8})
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            main(['--scenario', 'realms', '--map-size', '8'])
        self.assertEqual(exc.exception.code, 2)

    def test_cli_rejects_negative_enemy_count(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            main(['--scenario', 'expedition', '--enemy-count', '-1'])
        self.assertEqual(exc.exception.code, 2)

    def test_cli_reports_effective_configuration(self):
        fake_baseline = types.ModuleType('benchmark.expedition_baseline')
        fake_baseline.ExpeditionBaselineAgent = _Agent
        output = io.StringIO()
        with patch.dict(sys.modules, {'benchmark.expedition': _module(),
                                      'benchmark.expedition_baseline': fake_baseline}), \
                contextlib.redirect_stdout(output):
            status = main(['--scenario', 'expedition', '--agent', 'baseline', '--seeds', '9',
                           '--map-size', '8', '--quest-difficulty', 'hard',
                           '--combat-difficulty', 'easy', '--npc-difficulty', 'medium',
                           '--character-class', 'scout', '--map-topology', 'open',
                           '--terrain-diversity', '3', '--enemy-count', '2'])
        self.assertEqual(status, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report['engine_version'], 'test-expedition')
        self.assertEqual(report['component_versions'], {'map': 'test-map'})
        self.assertEqual(report['max_turns'], 321)
        self.assertEqual(report['config'], {
            'map_size': 8, 'map_topology': 'open', 'terrain_diversity': 3,
            'quest_difficulty': 'hard', 'combat_difficulty': 'easy',
            'npc_difficulty': 'medium', 'character_class': 'scout', 'enemy_count': 2,
        })
        self.assertEqual(report['runs'][0]['config'], report['config'])
        self.assertFalse(report['probes_enabled'])


if __name__ == '__main__':
    unittest.main()
