"""Behavioural checks for the multi-region adventure scenario."""
import json
import io
import os
import subprocess
import sys
import unittest
from unittest.mock import patch
from collections import Counter, deque

from benchmark.realms import Game, generate_world


class RealmsWorldTests(unittest.TestCase):
    def test_replay_deterministic_across_process_hash_seeds(self):
        code = r'''
import json
from benchmark.realms import Game
game = Game(42)
observations = [game.observe()]
for action in ({"type":"talk"}, {"type":"move","direction":"north"},
               {"type":"search"}, {"type":"attack"}, {"type":"move","direction":"down"}):
    observations.append(game.step(action))
print(json.dumps({"observations": observations, "result": game.result()}, sort_keys=True, ensure_ascii=False))
'''
        outputs = []
        for hash_seed in ('1', '8675309'):
            env = dict(os.environ, PYTHONHASHSEED=hash_seed)
            outputs.append(subprocess.check_output([sys.executable, '-c', code], env=env, text=True))
        self.assertEqual(outputs[0], outputs[1])

    def test_regions_are_large_connected_and_have_reciprocal_exits(self):
        opposite = {'north': 'south', 'south': 'north', 'east': 'west',
                    'west': 'east', 'up': 'down', 'down': 'up'}
        for seed in range(50):
            with self.subTest(seed=seed):
                world = generate_world(seed)
                rooms = world.rooms
                self.assertEqual(len({room.name for room in rooms}), len(rooms))
                sizes = Counter(room.zone for room in rooms)
                self.assertGreater(sizes['overworld'], 16)
                for zone in ('mountain', 'tower', 'dungeon'):
                    self.assertGreater(sizes[zone], 0)
                seen = {0}
                queue = deque([0])
                vertical = 0
                while queue:
                    here = queue.popleft()
                    for direction, dest in rooms[here].exits.items():
                        self.assertIn(direction, opposite)
                        self.assertEqual(rooms[dest].exits.get(opposite[direction]), here)
                        if direction in ('up', 'down'):
                            vertical += 1
                        if dest not in seen:
                            seen.add(dest)
                            queue.append(dest)
                self.assertEqual(len(seen), len(rooms))
                self.assertGreater(vertical, 0)

    def test_seed_changes_world_but_same_seed_and_actions_replay(self):
        signatures = []
        for seed in (3, 4, 5):
            world = generate_world(seed)
            signatures.append([(r.name, r.zone, sorted(r.exits.items())) for r in world.rooms])
        self.assertGreater(len({repr(s) for s in signatures}), 1)
        one, two = Game(123), Game(123)
        self.assertEqual(one.observe(), two.observe())
        for action in ({'type': 'talk'}, {'type': 'search'},
                       {'type': 'move', 'direction': 'north'}, {'type': 'defend'}):
            self.assertEqual(one.step(action), two.step(action))
        self.assertEqual(one.result(), two.result())

    def test_initial_observation_does_not_reveal_world_or_quests(self):
        game = Game(23)
        obs = game.observe()
        self.assertNotIn('world', obs)
        self.assertNotIn('quests', obs)
        self.assertNotIn('events', obs)
        self.assertNotIn('map', obs)
        self.assertNotIn('seed', obs)
        # Other room names must be discovered through play, not provided as a map.
        serialized = json.dumps(obs, ensure_ascii=False)
        for room in game.world.rooms[1:]:
            self.assertNotIn(room.name, serialized)

    def test_turn_budget_is_enforced(self):
        game = Game(23, max_turns=2)
        game.step({'type': 'not_an_action'})
        obs = game.step({'type': 'not_an_action'})
        self.assertTrue(obs['done'])
        self.assertEqual(game.result()['terminal_reason'], 'turn_limit')
        with self.assertRaises(RuntimeError):
            game.step({'type': 'talk'})


def _travel(game, destination):
    """Route on evaluator-only graph while advancing via the public game API."""
    queue = deque([(game.position, [])])
    seen = {game.position}
    while queue:
        room, path = queue.popleft()
        if room == destination:
            break
        for direction, target in game.world.rooms[room].exits.items():
            if target not in seen:
                seen.add(target)
                queue.append((target, path + [direction]))
    else:
        raise AssertionError('target unreachable')
    for direction in path:
        _clear_enemy(game)
        if game.hp <= game.max_hp - 6 and game.potions:
            game.step({'type': 'potion'})
        game.step({'type': 'move', 'direction': direction})
        if game.done:
            raise AssertionError(f'episode ended while traveling: {game.terminal_reason}')
    _clear_enemy(game)


def _clear_enemy(game):
    while game.observe()['enemy']:
        enemy = game.observe()['enemy']
        if game.hp <= 8 and game.potions:
            game.step({'type': 'potion'})
        elif (enemy['name'] == 'дракон' and enemy['intent'] == 'огненное дыхание'
              and enemy['hp'] > (5 if game.braced else 3)):
            game.step({'type': 'defend'})
        else:
            game.step({'type': 'attack'})
        if game.done:
            raise AssertionError(f'episode ended during combat: {game.terminal_reason}')


class RealmsGameplayTests(unittest.TestCase):
    def test_dragon_intent_signals_a_meaningful_defensive_choice(self):
        attack, defend = Game(123), Game(123)
        attack.position = attack.world.dragon_room
        defend.position = defend.world.dragon_room
        self.assertEqual(attack.observe()['enemy']['intent'], 'огненное дыхание')
        attack.step({'type': 'attack'})
        defend.step({'type': 'defend'})
        self.assertEqual(attack.hp, 12)
        self.assertEqual(defend.hp, 17)
        self.assertEqual(defend.observe()['enemy']['intent'], 'удар когтями')
        defend.step({'type': 'attack'})
        self.assertEqual(defend.observe()['enemy']['hp'], 11)

    def test_seal_prevents_relic_until_wizard_but_early_dragon_kill_is_recoverable(self):
        from benchmark.runner import aggregate_runs
        from benchmark.scoring import score
        for seed in range(10):
            with self.subTest(seed=seed):
                game = Game(seed)
                main = next(q for q in game.world.quests if q.key == 'main')
                game.step({'type': 'talk'})
                _travel(game, main.item_room)  # defeat dragon without obtaining the ward
                blocked = game.step({'type': 'search'})
                self.assertFalse(main.collected)
                self.assertIn('печать', blocked['message'].lower())
                self.assertNotIn(main.item, blocked['inventory'])
                _travel(game, game.world.wizard_room)
                game.step({'type': 'talk'})
                _travel(game, main.item_room)
                game.step({'type': 'search'})
                self.assertTrue(main.collected)
                _travel(game, main.giver_room)
                game.step({'type': 'talk'})
                result = game.result()
                self.assertEqual(result['terminal_reason'], 'completed')
                self.assertEqual(result['side_quests_completed'], 0)
                measured = score(result)
                self.assertEqual(measured['outcomes']['quests']['completion_rate'], 0.5)
                self.assertTrue(measured['outcomes']['quests']['main_completed'])
                self.assertEqual(aggregate_runs([{'score': measured}])['main_quest_success']['mean'], 1.0)

    def test_main_and_optional_quest_are_solvable_with_public_actions(self):
        for seed in range(30):
            with self.subTest(seed=seed):
                game = Game(seed)
                main = next(q for q in game.world.quests if q.key == 'main')
                side = next(q for q in game.world.quests if q.key == 'side')
                game.step({'type': 'talk'})
                self.assertTrue(main.accepted)
                _travel(game, side.giver_room)
                game.step({'type': 'talk'})
                _travel(game, side.item_room)
                game.step({'type': 'search'})
                _travel(game, side.giver_room)
                potions_before = game.potions
                game.step({'type': 'talk'})
                self.assertTrue(side.completed)
                self.assertEqual(game.potions, potions_before + 2)
                _travel(game, game.world.wizard_room)
                game.step({'type': 'talk'})
                self.assertIn('рунический оберег', game.observe()['inventory'])
                _travel(game, main.item_room)
                game.step({'type': 'search'})
                self.assertTrue(main.collected)
                _travel(game, main.giver_room)
                game.step({'type': 'talk'})
                self.assertEqual(game.result()['terminal_reason'], 'completed')
                self.assertTrue(game.result()['main_quest_completed'])
                self.assertEqual(game.result()['side_quests_completed'], 1)
                self.assertLessEqual(game.turn, game.max_turns)


class RealmsRunnerTests(unittest.TestCase):
    def test_cli_selects_scenario_and_default_turn_limit(self):
        output = subprocess.check_output(
            [sys.executable, '-m', 'benchmark.runner', '--agent', 'baseline',
             '--scenario', 'realms', '--seeds', '1'], text=True)
        report = json.loads(output)
        self.assertEqual(report['scenario'], 'realms')
        self.assertEqual(report['engine_version'], 'realms-0.1.0')
        self.assertEqual(report['max_turns'], 300)
        self.assertEqual(report['runs'][0]['scenario'], 'realms')
        self.assertEqual(report['runs'][0]['result']['terminal_reason'], 'completed')
        self.assertEqual(report['runs'][0]['result']['invalid_actions'], 0)

    def test_direct_openai_agent_uses_rules_of_the_scenario(self):
        from benchmark.runner import OpenAICompatibleAgent, run_episode
        from benchmark.realms import SYSTEM_PROMPT
        captured = []
        def urlopen(request, timeout):
            captured.append(json.loads(request.data))
            response = {'choices': [{'message': {'content': '{"type":"talk"}'}}]}
            return io.BytesIO(json.dumps(response).encode())
        agent = OpenAICompatibleAgent('fake', 'https://example.test', 'fake-key')
        with patch('urllib.request.urlopen', side_effect=urlopen):
            run_episode(1, agent, max_turns=1, probes=False, scenario='realms')
        self.assertEqual(captured[0]['messages'][0]['content'], SYSTEM_PROMPT)

    def test_model_receives_scenario_rules_and_no_world_state(self):
        from benchmark.runner import main
        from benchmark.realms import SYSTEM_PROMPT
        captured = []
        def urlopen(request, timeout):
            captured.append(json.loads(request.data))
            response = {'choices': [{'message': {'content': '{"type":"talk"}'}}]}
            return io.BytesIO(json.dumps(response).encode())
        stdout = io.StringIO()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fake-key'}), \
                patch('urllib.request.urlopen', side_effect=urlopen), \
                patch('sys.stdout', stdout):
            code = main(['--scenario', 'realms', '--agent', 'openai', '--model', 'fake',
                         '--seeds', '1', '--max-turns', '1', '--no-probes'])
        self.assertEqual(code, 0)
        self.assertEqual(len(captured), 1)
        messages = captured[0]['messages']
        self.assertEqual(messages[0]['content'], SYSTEM_PROMPT)
        obs = json.loads(messages[1]['content'])
        self.assertEqual(obs['zone'], 'overworld')
        self.assertNotIn('world', obs)
        self.assertNotIn('quests', obs)
        self.assertEqual(json.loads(stdout.getvalue())['scenario'], 'realms')


if __name__ == '__main__':
    unittest.main()
