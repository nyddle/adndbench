import unittest

from benchmark.caravan import (ENGINE_VERSION, MIN_MAX_TURNS, TURN_SLACK, Game,
                               generate_world, oracle_turns, _distances)


class OracleAgent:
    """Evaluator-only full-information player; proves every seed is solvable."""

    def __init__(self, game):
        self.game = game

    def _path(self, target):
        world = self.game.world
        start = self.game.position
        if start == target:
            return []
        dist = _distances(world, target)
        path, room = [], start
        while room != target:
            direction, nxt = min(world.rooms[room].exits.items(), key=lambda kv: dist[kv[1]])
            path.append(direction)
            room = nxt
        return path

    def _step(self, action):
        """One action unless the game is already over; returns the observation or None."""
        if self.game.done:
            return None
        return self.game.step(action)

    def _next_stage(self):
        """Nearest next objective among unfinished quests; the main quest goes last."""
        game, world = self.game, self.game.world
        pending = [q for q in world.quests[1:] if not q.completed]
        main_open = not world.quests[0].completed
        if not pending and main_open:
            pending = [world.quests[0]]
        if not pending:
            return None
        dist = _distances(world, game.position)
        best = None
        for quest in pending:
            if not quest.accepted:
                stage = (quest.giver_room, 'talk')
            elif not quest.collected:
                stage = (quest.item_room, 'search')
            else:
                stage = (quest.giver_room, 'talk')
            if best is None or dist[stage[0]] < dist[best[0]]:
                best = stage
        return best

    def solve(self):
        game = self.game
        while not game.done:
            stage = self._next_stage()
            if stage is None:
                break
            target, act = stage
            obs = game.observe()
            if obs['hp'] <= 10 and obs['rations'] and game.position != 0:
                for direction in self._path(0):
                    obs = self._step({'type': 'move', 'direction': direction})
                    if obs is None:
                        return
            elif game.position != target:
                for direction in self._path(target):
                    obs = self._step({'type': 'move', 'direction': direction})
                    if obs is None:
                        return
            while obs and obs.get('enemy'):
                if obs['hp'] <= 6 and obs['potions']:
                    obs = self._step({'type': 'potion'})
                else:
                    obs = self._step({'type': 'attack'})
            if game.done:
                return
            if game.position == target:
                obs = self._step({'type': act})
            if game.position == 0 and obs and obs['rations'] and obs['hp'] <= 10:
                self._step({'type': 'rest'})


class CaravanTest(unittest.TestCase):
    def test_determinism_and_variation(self):
        first, again, other = generate_world(1), generate_world(1), generate_world(2)
        signature = lambda w: ([r.name for r in w.rooms],
                               [(q.giver, q.giver_room, q.item, q.item_room, q.reward) for q in w.quests],
                               w.rumors)
        self.assertEqual(signature(first), signature(again))
        self.assertNotEqual(signature(first), signature(other))
        for bad in (None, True, 1.5):
            with self.assertRaises(ValueError):
                Game(bad)
        with self.assertRaises(ValueError):
            Game(1, max_turns=0)

    def test_connectivity_and_placement(self):
        for seed in range(1, 11):
            world = generate_world(seed)
            self.assertEqual(len(world.rooms), 64)
            self.assertTrue(all(d >= 0 for d in _distances(world, 0)))
            givers = [q.giver_room for q in world.quests]
            items = [q.item_room for q in world.quests]
            self.assertEqual(len(set(givers + items)), len(givers + items))
            self.assertEqual(sum(r.npc is not None for r in world.rooms), 14)
            self.assertEqual(len(world.quests), 10)
            # Interference is structural: ten items over five adjectives force a shared stem.
            adjectives = [q.item.split()[0] for q in world.quests]
            self.assertLess(len(set(adjectives)), len(adjectives))
            for room_index in world.rumors:
                self.assertIsNotNone(world.rooms[room_index].npc)

    def test_observation_has_no_hidden_state(self):
        game = Game(1)
        obs = game.observe()
        self.assertEqual(set(obs), {'room', 'district', 'exits', 'npc', 'enemy', 'hp', 'max_hp',
                                    'inventory', 'potions', 'rations', 'turn', 'max_turns',
                                    'message', 'done'})
        game.step({'type': 'talk'})
        obs = game.observe()
        self.assertNotIn('quests', obs)
        self.assertNotIn('seed', obs)
        # Rumour rooms do not reveal their target until visited and talked to.
        self.assertNotIn('rumors', obs)

    def test_quest_protocol_and_rewards(self):
        game = Game(1)
        main = game.world.quests[0]
        # Search before accepting finds nothing; the item room stays unrevealed in obs.
        game.position = main.item_room
        game.world.rooms[main.item_room].enemy_hp = 0
        self.assertEqual(game.step({'type': 'search'})['message'], 'Вы не нашли ничего полезного.')
        game.position = 0
        obs = game.step({'type': 'talk'})
        self.assertIn(main.item, obs['message'])
        self.assertIn('Я не повторю поручение', obs['message'])
        game.position = main.item_room
        game.step({'type': 'search'})
        self.assertIn(main.item, game.inventory)
        game.position = 0
        obs = game.step({'type': 'talk'})
        # 0.2.0: сдача главного квеста не завершает игру, пока есть сайды.
        self.assertFalse(game.done)
        for quest in game.world.quests[1:]:
            quest.completed = True
        game.step({'type': 'search'})
        self.assertTrue(game.done)
        self.assertEqual(game.terminal_reason, 'completed')
        with self.assertRaises(RuntimeError):
            game.step({'type': 'talk'})
        # Side reward application on a fresh game.
        game = Game(2)
        side = next(q for q in game.world.quests[1:] if q.reward == 'potion')
        potions = game.potions
        side.accepted, side.collected = True, True
        game.inventory.append(side.item)
        game.position = side.giver_room
        obs = game.step({'type': 'talk'})
        self.assertEqual(game.potions, potions + 1)
        self.assertIn('Вы получили зелье', obs['message'])

    def test_rumour_is_one_shot_and_truthful(self):
        game = Game(1)
        room_index = next(iter(game.world.rumors))
        game.position = room_index
        obs = game.step({'type': 'talk'})
        target = game.world.quests[game.world.rumors[room_index]]
        self.assertIn(target.item, obs['message'])
        self.assertIn(game.world.rooms[target.item_room].name, obs['message'])
        self.assertIn('уже всё рассказал', game.step({'type': 'talk'})['message'])

    def test_invalid_actions_and_turn_limit(self):
        game = Game(1, max_turns=3)
        obs = game.step({'type': 'move', 'direction': 'north'})  # may be valid; force invalid next
        obs = game.step({'type': 'fly'})
        self.assertEqual(obs['message'], 'Неизвестное действие.')
        game.step({'type': 'search'})
        self.assertTrue(game.done)
        self.assertEqual(game.terminal_reason, 'turn_limit')
        self.assertGreaterEqual(game.result()['invalid_actions'], 1)

    def test_oracle_solves_within_budget(self):
        for seed in range(1, 11):
            game = Game(seed)
            OracleAgent(game).solve()
            result = game.result()
            self.assertEqual(result['terminal_reason'], 'completed', f'seed {seed}')
            self.assertEqual(result['side_quests_completed'], 9, f'seed {seed}')
            self.assertLessEqual(result['turns'], game.max_turns, f'seed {seed}')

    def test_max_turns_scales_with_oracle(self):
        for seed in range(1, 11):
            game = Game(seed)
            estimate = oracle_turns(game.world)
            self.assertEqual(game.max_turns, max(MIN_MAX_TURNS, TURN_SLACK * estimate))
            self.assertLess(estimate, game.max_turns)

    def test_result_shape(self):
        game = Game(1)
        game.step({'type': 'search'})
        result = game.result()
        self.assertEqual(result['engine_version'], ENGINE_VERSION)
        self.assertEqual(result['quests_total'], 10)
        self.assertEqual(result['side_quests_total'], 9)
        self.assertFalse(result['main_quest_completed'])
        self.assertEqual(result['rooms_total'], 64)


if __name__ == '__main__':
    unittest.main()
