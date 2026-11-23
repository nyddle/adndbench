"""Reproducibility and environment invariants for the game engine."""
import json
import os
import subprocess
import sys
import unittest
from collections import deque
from dataclasses import asdict

from benchmark.engine import Game


class ReproducibilityTests(unittest.TestCase):
    def test_same_seed_and_actions_have_same_observations_and_result(self):
        actions = [
            {"type": "talk"},
            {"type": "search"},
            {"type": "move", "direction": "north"},
            {"type": "attack"},
            {"type": "defend"},
            {"type": "potion"},
            {"type": "rest"},
            {"type": "move", "direction": "west"},
        ]
        first, second = Game(987654321), Game(987654321)
        self.assertEqual(first.observe(), second.observe())
        for action in actions:
            self.assertEqual(first.step(action), second.step(action))
        self.assertEqual(first.result(), second.result())

    def test_reproducible_across_python_hash_seeds(self):
        code = r'''
import json
from benchmark.engine import Game
game = Game(42)
observations = [game.observe()]
for action in [{"type":"talk"}, {"type":"move","direction":"north"},
               {"type":"search"}, {"type":"attack"}]:
    observations.append(game.step(action))
print(json.dumps({"observations": observations, "result": game.result()}, sort_keys=True))
'''
        outputs = []
        for hash_seed in ("1", "1234567"):
            env = dict(os.environ, PYTHONHASHSEED=hash_seed)
            outputs.append(subprocess.check_output([sys.executable, "-c", code], env=env, text=True))
        self.assertEqual(outputs[0], outputs[1])

    def test_distinct_seeds_change_worlds(self):
        # This is a smoke test over several seeds, not a claim that seed collisions are impossible.
        worlds = {json.dumps(asdict(Game(seed).world), sort_keys=True) for seed in range(5)}
        self.assertGreater(len(worlds), 1)


def travel(game, destination):
    """Evaluator-only path follower used to validate generated scenarios."""
    queue = deque([(game.position, [])])
    seen = {game.position}
    while queue:
        position, path = queue.popleft()
        if position == destination:
            break
        for direction, target in game.world.rooms[position].exits.items():
            if target not in seen:
                seen.add(target)
                queue.append((target, path + [direction]))
    else:
        raise AssertionError("unreachable room")
    for direction in path:
        while game.observe()["enemy"]:
            if game.hp <= 6 and game.potions:
                game.step({"type": "potion"})
            game.step({"type": "attack"})
        game.step({"type": "move", "direction": direction})
        if game.done:
            raise AssertionError(f"episode ended while traveling: {game.terminal_reason}")


class ScenarioTests(unittest.TestCase):
    def test_worlds_are_connected_and_have_reciprocal_exits(self):
        from benchmark.engine import OPPOSITE, shortest_distance

        for seed in range(50):
            game = Game(seed)
            for room_id, room in enumerate(game.world.rooms):
                self.assertGreaterEqual(shortest_distance(game.world, 0, room_id), 0)
                for direction, target in room.exits.items():
                    self.assertEqual(game.world.rooms[target].exits[OPPOSITE[direction]], room_id)

    def test_quests_can_be_completed_through_public_actions(self):
        # Path selection is privileged here; only actual game actions advance the world.
        for seed in range(20):
            game = Game(seed, max_turns=500)
            for quest in game.world.quests:
                travel(game, quest.giver_room)
                game.step({"type": "talk"})
                travel(game, quest.item_room)
                while game.observe()["enemy"]:
                    if game.hp <= 6 and game.potions:
                        game.step({"type": "potion"})
                    game.step({"type": "attack"})
                game.step({"type": "search"})
                travel(game, quest.giver_room)
                game.step({"type": "talk"})
            self.assertEqual(game.result()["terminal_reason"], "completed", msg=f"seed={seed}")

    def test_quests_and_world_are_not_in_initial_observation(self):
        game = Game(42)
        observation = game.observe()
        self.assertNotIn("world", observation)
        self.assertNotIn("quests", observation)
        self.assertNotIn("events", observation)
        text = json.dumps(observation, ensure_ascii=False)
        for quest in game.world.quests:
            self.assertNotIn(quest.item, text)
            self.assertNotIn(game.world.rooms[quest.item_room].name, text)
        quest = game.world.quests[0]
        travel(game, quest.giver_room)
        first = game.step({"type": "talk"})
        second = game.step({"type": "talk"})
        self.assertIn(quest.item, first["message"])
        self.assertIn(game.world.rooms[quest.item_room].name, first["message"])
        self.assertNotIn(quest.item, second["message"])
        self.assertNotIn(game.world.rooms[quest.item_room].name, second["message"])


if __name__ == "__main__":
    unittest.main()
