"""Cross-scenario regression and integration tests.

Recorded trajectories are generated artifacts, not expectations recomputed by
this test. They exercise the public action interface and protect benchmark
version reproducibility across future scenario integrations.
"""
import io
import json
import os
import subprocess
import sys
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from benchmark.engine import Game as ClassicGame
from benchmark.realms import Game as RealmsGame


ROOT = Path(__file__).resolve().parents[1]


class HistoricalReplayTests(unittest.TestCase):
    def test_saved_classic_and_realms_episodes_replay_exactly(self):
        cases = [
            (ClassicGame, 'experiments/codex_pilot/strong_seed1.jsonl', 1, 120),
            (ClassicGame, 'experiments/codex_pilot/small_seed2.jsonl', 2, 120),
            (RealmsGame, 'experiments/realms_codex_pilot/luna56_seed2.jsonl', 2, 300),
            (RealmsGame, 'experiments/realms_codex_pilot/luna6_seed3.jsonl', 3, 300),
        ]
        for game_class, relative_path, seed, budget in cases:
            with self.subTest(path=relative_path):
                rows = [json.loads(line) for line in (ROOT / relative_path).read_text(encoding='utf-8').splitlines()]
                game = game_class(seed, max_turns=budget)
                self.assertEqual(game.observe(), rows[0]['observation'])
                for row in rows[1:]:
                    self.assertEqual(game.step(row['action']), row['observation'])
                self.assertTrue(game.observe()['done'])
                self.assertEqual(game.result()['terminal_reason'], 'completed')


class ExpeditionIntegrationTests(unittest.TestCase):
    @staticmethod
    def _geometry(game):
        # Privileged inspection here belongs to the evaluator, never the player.
        return sorted((room['id'], room['name'], room['zone'],
                       sorted(room['exits'].items())) for room in game.world['rooms'])

    def test_initial_observation_is_partial_and_versions_are_separate(self):
        from benchmark.expedition import Game, ENGINE_VERSION
        from benchmark.realms import ENGINE_VERSION as REALMS_VERSION
        game = Game(1, max_turns=20, map_size=6, quest_difficulty='medium',
                    combat_difficulty='medium', character_class='generalist',
                    npc_difficulty='medium')
        obs = game.observe()
        self.assertNotEqual(ENGINE_VERSION, REALMS_VERSION)
        self.assertIsInstance(obs, dict)
        self.assertFalse(obs['done'])
        for private_key in ('world', 'seed', 'map', 'events', 'answer_key'):
            self.assertNotIn(private_key, obs)
        self.assertIsInstance(obs.get('exits'), list)

    def test_same_seed_configuration_and_actions_replay_across_processes(self):
        script = r'''
import json
from benchmark.expedition import Game
game = Game(17, max_turns=25, map_size=8, quest_difficulty='medium',
            combat_difficulty='medium', character_class='generalist', npc_difficulty='medium')
observations = [game.observe()]
for i in range(8):
    obs = game.observe()
    action = {'type': 'talk'} if i == 0 else {'type': 'move', 'direction': obs['exits'][0]}
    observations.append(game.step(action))
    if game.observe()['done']:
        break
print(json.dumps({'observations': observations, 'result': game.result()}, sort_keys=True, ensure_ascii=False))
'''
        outputs = []
        for hash_seed in ('1', '8675309'):
            env = dict(os.environ, PYTHONHASHSEED=hash_seed)
            outputs.append(subprocess.check_output([sys.executable, '-c', script], env=env, text=True))
        self.assertEqual(outputs[0], outputs[1])

    def test_changing_non_map_axes_does_not_change_map_geometry(self):
        from benchmark.expedition import Game
        baseline = {'map_size': 6, 'quest_difficulty': 'medium',
                    'combat_difficulty': 'medium', 'character_class': 'generalist',
                    'npc_difficulty': 'medium'}
        reference = self._geometry(Game(17, **baseline))
        for axis, value in (('quest_difficulty', 'hard'), ('combat_difficulty', 'hard'),
                            ('character_class', 'warrior'), ('npc_difficulty', 'hard')):
            with self.subTest(axis=axis):
                config = {**baseline, axis: value}
                game = Game(17, **config)
                self.assertEqual(game.config[axis], value)
                self.assertEqual(self._geometry(game), reference)

    def test_changing_one_axis_does_not_randomize_unrelated_subsystems(self):
        from benchmark.expedition import Game
        base = Game(17)
        more_quests = Game(17, quest_difficulty='hard')
        self.assertNotEqual(more_quests.plan, base.plan)
        self.assertEqual(more_quests.encounters, base.encounters)
        harder_combat = Game(17, combat_difficulty='hard')
        self.assertNotEqual(harder_combat.encounters, base.encounters)
        self.assertEqual(harder_combat.plan, base.plan)
        self.assertEqual(harder_combat.npc_knowledge, base.npc_knowledge)
        harder_npcs = Game(17, npc_difficulty='hard')
        self.assertNotEqual(harder_npcs.npc_knowledge, base.npc_knowledge)
        self.assertEqual(harder_npcs.plan, base.plan)
        self.assertEqual(harder_npcs.encounters, base.encounters)
        mage = Game(17, character_class='mage')
        self.assertEqual(mage.plan, base.plan)
        self.assertEqual(mage.encounters, base.encounters)
        self.assertEqual(mage.npc_knowledge, base.npc_knowledge)

    def test_map_sizes_change_overworld_but_keep_all_regions_connected(self):
        from benchmark.expedition import Game
        sizes = []
        for size in (6, 8, 10):
            with self.subTest(size=size):
                game = Game(8, map_size=size)
                rooms = {room['id']: room for room in game.world['rooms']}
                self.assertEqual(len(rooms), len(game.world['rooms']))
                self.assertEqual(sum(r['zone'] == 'overworld' for r in rooms.values()), size * size)
                self.assertEqual({r['zone'] for r in rooms.values()},
                                 {'overworld', 'mountain', 'tower', 'dungeon'})
                seen = {game.world['sites']['elder']}
                pending = list(seen)
                while pending:
                    room = rooms[pending.pop()]
                    for target in room['exits'].values():
                        self.assertIn(target, rooms)
                        if target not in seen:
                            seen.add(target)
                            pending.append(target)
                self.assertEqual(seen, set(rooms))
                sizes.append(len(rooms))
        self.assertEqual(sizes, sorted(set(sizes)))

    def test_axes_change_the_generated_scenario_not_just_config(self):
        from benchmark.expedition import Game
        easy = Game(17, quest_difficulty='easy', combat_difficulty='easy')
        hard = Game(17, quest_difficulty='hard', combat_difficulty='hard')
        self.assertGreater(len(hard.plan['quests']), len(easy.plan['quests']))
        self.assertGreater(sum(len(q['objectives']) for q in hard.plan['quests']),
                           sum(len(q['objectives']) for q in easy.plan['quests']))
        self.assertGreater(len(hard.encounters), len(easy.encounters))
        abilities = {}
        for class_id in ('generalist', 'warrior', 'mage', 'scout'):
            obs = Game(17, character_class=class_id).observe()
            self.assertEqual(obs['character']['class_id'], class_id)
            abilities[class_id] = obs['character']['abilities'][0]['id']
        self.assertEqual(len(set(abilities.values())), 4)

        npc_easy = Game(17, quest_difficulty='hard', npc_difficulty='easy').npc_knowledge['npcs']
        npc_hard = Game(17, quest_difficulty='hard', npc_difficulty='hard').npc_knowledge['npcs']
        def fact_holders(knowledge):
            return {topic: npc_id for npc_id, npc in knowledge.items()
                    for topic in npc['topics'] if topic.startswith('quest:')}
        easy_holders, hard_holders = fact_holders(npc_easy), fact_holders(npc_hard)
        self.assertEqual(set(easy_holders), set(hard_holders))
        self.assertNotEqual(easy_holders, hard_holders)

    def test_npc_topic_reveals_only_an_actually_grounded_fact(self):
        from benchmark.expedition import Game
        game = Game(11, quest_difficulty='easy', npc_difficulty='easy')
        wizard_id = game.world['sites']['wizard']
        wizard_name = next(r['name'] for r in game.world['rooms'] if r['id'] == wizard_id)
        obs = game.observe()
        self.assertNotIn(wizard_name, json.dumps(obs['topics'], ensure_ascii=False))
        topic = next(t for t in obs['topics'] if t['id'] == 'quest:main:main_ward')
        answer = game.step({'type': 'ask', 'topic': topic['id']})
        self.assertIn(wizard_name, answer['message'])
        self.assertFalse(game.result()['invalid_actions'])

    def test_npc_facts_are_available_only_from_the_current_informed_npc(self):
        from benchmark.expedition import Game
        game = Game(19, quest_difficulty='hard', npc_difficulty='hard')
        initial = game.observe()
        self.assertEqual(initial['npc'], 'Старейшина')
        local_topics = {topic['id'] for topic in initial['topics']}
        remote_fact = next((topic for npc_id, npc in game.npc_knowledge['npcs'].items()
                            if npc_id != 'elder' for topic_id, topic in npc['topics'].items()
                            if topic_id.startswith('quest:') and topic_id not in local_topics), None)
        self.assertIsNotNone(remote_fact, 'Hard profile must distribute at least one fact')
        self.assertNotIn(remote_fact['id'], local_topics)
        self.assertNotIn(remote_fact['message'], json.dumps(initial, ensure_ascii=False))
        answer = game.step({'type': 'ask', 'topic': remote_fact['id']})
        self.assertNotIn(remote_fact['message'], answer['message'])
        self.assertEqual(game.result()['invalid_actions'], 1)

    def test_scout_recon_only_reveals_adjacent_locations_and_costs_energy(self):
        from benchmark.expedition import Game
        game = Game(12, character_class='scout')
        initial = game.observe()
        rooms = {r['id']: r for r in game.world['rooms']}
        neighbours = set(rooms[game.position]['exits'].values())
        revealed = game.step({'type': 'ability', 'ability': 'recon'})
        self.assertLess(revealed['character']['energy'], initial['character']['energy'])
        self.assertGreater(revealed['character']['abilities'][0]['cooldown_remaining'], 0)
        for rid, room in rooms.items():
            if rid in neighbours:
                self.assertIn(room['name'], revealed['message'])
            elif rid != game.position:
                self.assertNotIn(room['name'], revealed['message'])
        energy = revealed['character']['energy']
        game.step({'type': 'ability', 'ability': 'recon'})
        self.assertEqual(game.result()['invalid_actions'], 1)
        self.assertEqual(game.observe()['character']['energy'], energy)

    def test_class_abilities_respect_visible_enemy_resistance(self):
        from benchmark.expedition import Game
        # Find a reachable phase-zero shield encounter without using any
        # privileged state to make a game transition.
        selected = None
        for seed in range(20):
            game = Game(seed, character_class='mage', combat_difficulty='easy')
            rooms = {r['id']: r for r in game.world['rooms']}
            candidates = {rid for rid, encounter in game.encounters.items()
                          if encounter['kind'] == 'sentinel'}
            blocked = set(game.encounters) - candidates
            queue, seen = deque([(game.position, [])]), {game.position}
            while queue:
                current, path = queue.popleft()
                if current in candidates:
                    selected = (seed, path)
                    break
                for direction, dest in rooms[current]['exits'].items():
                    if dest not in seen and dest not in blocked:
                        seen.add(dest)
                        queue.append((dest, path + [direction]))
            if selected:
                break
        self.assertIsNotNone(selected, 'No reachable shield encounter in fixture seeds')
        seed, path = selected
        outcomes = {}
        for class_id, ability in (('mage', 'fire_bolt'), ('warrior', 'heavy_strike')):
            game = Game(seed, character_class=class_id, combat_difficulty='easy')
            for direction in path:
                game.step({'type': 'move', 'direction': direction})
            before = game.observe()
            self.assertEqual(before['enemy']['intent']['physical_damage_cap'], 1)
            after = game.step({'type': 'ability', 'ability': ability})
            self.assertLess(after['character']['energy'], before['character']['energy'])
            outcomes[class_id] = before['enemy']['hp'] - after['enemy']['hp']
            self.assertEqual(game.result()['invalid_actions'], 0)
        self.assertEqual(outcomes, {'mage': 7, 'warrior': 1})
        # The same encounter on hard resists fire as well, even with the
        # number and placement of monsters held fixed.
        game = Game(seed, character_class='mage', combat_difficulty='hard', enemy_count=2)
        for direction in path:
            game.step({'type': 'move', 'direction': direction})
        before = game.observe()
        self.assertEqual(before['enemy']['intent']['fire_damage_cap'], 1)
        after = game.step({'type': 'ability', 'ability': 'fire_bolt'})
        self.assertEqual(before['enemy']['hp'] - after['enemy']['hp'], 1)

    def test_cli_passes_selected_profile_and_hides_world_from_model(self):
        from benchmark.runner import main
        requests = []
        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data))
            return io.BytesIO(json.dumps({'choices': [{'message': {'content': '{"type":"talk"}'}}]}).encode())
        stdout = io.StringIO()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}), \
                patch('urllib.request.urlopen', side_effect=fake_urlopen), \
                patch('sys.stdout', stdout):
            code = main(['--scenario', 'expedition', '--agent', 'openai', '--model', 'mock',
                         '--seeds', '17', '--map-size', '8', '--quest-difficulty', 'hard',
                         '--combat-difficulty', 'easy', '--character-class', 'scout',
                         '--npc-difficulty', 'medium', '--max-turns', '1', '--no-probes'])
        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report['scenario'], 'expedition')
        self.assertEqual(report['max_turns'], 1)
        self.assertEqual(report['config']['map_size'], 8)
        self.assertEqual(report['config']['quest_difficulty'], 'hard')
        self.assertEqual(report['config']['combat_difficulty'], 'easy')
        self.assertEqual(report['config']['character_class'], 'scout')
        self.assertEqual(report['config']['npc_difficulty'], 'medium')
        self.assertEqual(len(requests), 1)
        observation = json.loads(requests[0]['messages'][1]['content'])
        for private_key in ('seed', 'world', 'map', 'events', 'answer_key'):
            self.assertNotIn(private_key, observation)

    def test_generated_main_quests_are_solvable_through_public_actions(self):
        """Use an evaluator-only route oracle, not a benchmark player.

        Routes and prerequisites are privileged to establish world solvability;
        all state transitions still happen through Game.step().
        """
        from benchmark.expedition import Game

        def fight(game):
            while game.observe()['enemy']:
                enemy = game.observe()['enemy']
                intent = enemy['intent']
                if game.hp <= 8 and game.potions and intent['damage'] <= 2:
                    action = {'type': 'potion'}
                elif (not game.braced and intent['damage'] > 1
                      and enemy['hp'] > 3):
                    action = {'type': 'defend'}
                else:
                    action = {'type': 'attack'}
                game.step(action)
                self.assertNotEqual(game.terminal_reason, 'death')
                self.assertNotEqual(game.terminal_reason, 'turn_limit')

        def travel(game, target):
            rooms = {r['id']: r for r in game.world['rooms']}
            blocked = {rid for rid, enemy in game.encounters.items()
                       if enemy['hp'] > 0 and rid != target}
            queue = deque([(game.position, [])])
            seen = {game.position}
            while queue:
                current, path = queue.popleft()
                if current == target:
                    break
                for direction, dest in rooms[current]['exits'].items():
                    if dest not in seen and dest not in blocked:
                        seen.add(dest)
                        queue.append((dest, path + [direction]))
            else:
                self.fail(f'No safe path from {game.position} to {target}')
            for direction in path:
                fight(game)
                game.step({'type': 'move', 'direction': direction})
                self.assertNotEqual(game.terminal_reason, 'death')
                self.assertNotEqual(game.terminal_reason, 'turn_limit')
            fight(game)

        profiles = [(seed, 6, 'generalist', difficulty)
                    for seed in (0, 1, 2, 17, 99) for difficulty in ('easy', 'medium')]
        profiles += [(seed, size, class_id, 'hard')
                     for seed in (0, 1, 2, 17, 99)
                     for size in (6, 8, 10)
                     for class_id in ('generalist', 'warrior', 'mage', 'scout')]
        for seed, size, class_id, difficulty in profiles:
            with self.subTest(seed=seed, size=size, class_id=class_id, difficulty=difficulty):
                game = Game(seed, max_turns=600, map_size=size, character_class=class_id,
                            quest_difficulty=difficulty, combat_difficulty='hard', npc_difficulty='hard')
                required = [q for q in game.plan['quests'] if q['required']]
                objectives = [o for q in required for o in q['objectives']]
                while not game.done:
                    done = set(game.quest_state['completed_objectives'])
                    eligible = [o for o in objectives if o['id'] not in done
                                and set(o['requires']) <= done]
                    self.assertTrue(eligible, 'Required objective graph is blocked')
                    objective = eligible[0]
                    travel(game, objective['room_id'])
                    if objective['id'] in game.quest_state['completed_objectives']:
                        continue  # defeating the target may advance the objective
                    action = {'type': objective['event']}
                    self.assertIn(action['type'], ('talk', 'search'))
                    game.step(action)
                    self.assertIn(objective['id'], game.quest_state['completed_objectives'])
                result = game.result()
                self.assertEqual(result['terminal_reason'], 'completed')
                self.assertTrue(result['main_quest_completed'])
                self.assertEqual(result['invalid_actions'], 0)


if __name__ == '__main__':
    unittest.main()
