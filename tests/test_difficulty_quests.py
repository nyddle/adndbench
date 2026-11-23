"""Quest dependency, determinism, and event-state behaviour."""
import json
import os
import subprocess
import sys
import unittest
from copy import deepcopy

from benchmark.difficulty.quests import (advance, eligible_objectives, generate_quests,
                                         initial_state, required_complete, validate_plan)


def world_fixture():
    rooms = []
    for zone, count in (("overworld", 12), ("mountain", 8), ("tower", 4), ("dungeon", 5)):
        for i in range(count):
            rooms.append({"id": f"{zone}-{i}", "name": f"{zone} room {i}", "zone": zone, "exits": {}})
    for left, right in zip(rooms, rooms[1:]):
        left["exits"]["east"] = right["id"]
        right["exits"]["west"] = left["id"]
    return {"rooms": rooms, "sites": {
        "elder": "overworld-0", "herbalist": "overworld-1", "wizard": "tower-0",
        "dragon": "dungeon-0", "herb": "mountain-0", "bandit": "overworld-2", "guard": "mountain-1",
        "mountain_gate": "overworld-3", "mountain_entry": "mountain-2", "tower_gate": "mountain-3",
        "tower_entry": "tower-1", "dungeon_gate": "overworld-4", "dungeon_entry": "dungeon-1",
    }}


def event_for(plan, objective_id):
    obj = next(o for q in plan["quests"] for o in q["objectives"] if o["id"] == objective_id)
    return {key: obj[key] for key in ("event", "target_id", "room_id")}


class QuestGenerationTests(unittest.TestCase):
    def test_seed_profile_and_map_have_expected_graph(self):
        world = world_fixture()
        for difficulty, count in (("easy", 2), ("medium", 3), ("hard", 4)):
            with self.subTest(difficulty=difficulty):
                plan = generate_quests(31, world, difficulty)
                self.assertEqual(plan, generate_quests("31", world, difficulty))
                self.assertEqual(len(plan["quests"]), count)
                validate_plan(plan, world)
                self.assertEqual(plan["quests"][0]["id"], "main")
                self.assertTrue(plan["quests"][0]["required"])
                self.assertEqual({npc["id"] for npc in plan["npcs"]} >= {"elder", "wizard", "herbalist"}, True)
                self.assertEqual(len({npc["room_id"] for npc in plan["npcs"]}), len(plan["npcs"]))
        self.assertNotEqual(generate_quests(1, world, "hard"), generate_quests(2, world, "hard"))

    def test_seeded_plans_stable_across_process_hash_seeds(self):
        code = r'''import json
from benchmark.difficulty.quests import generate_quests
world = json.loads(input())
print(json.dumps(generate_quests('abc', world, 'hard'), ensure_ascii=False, sort_keys=True))'''
        outputs = []
        for seed in ("1", "8675309"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            outputs.append(subprocess.check_output([sys.executable, "-c", code], env=env,
                            input=json.dumps(world_fixture()), text=True))
        self.assertEqual(outputs[0], outputs[1])

    def test_bad_inputs_and_cycles_are_rejected(self):
        world = world_fixture()
        for seed in (True, 1.5):
            with self.assertRaises(ValueError):
                generate_quests(seed, world)
        with self.assertRaises(ValueError):
            generate_quests(1, world, "unknown")
        broken = deepcopy(world)
        broken["sites"]["dragon"] = "not-a-room"
        with self.assertRaises(ValueError):
            generate_quests(1, broken)
        broken = deepcopy(world)
        broken["rooms"][0]["exits"] = {}
        broken["rooms"][1]["exits"].pop("west")
        with self.assertRaisesRegex(ValueError, "connected"):
            generate_quests(1, broken)
        plan = generate_quests(1, world, "hard")
        first = plan["quests"][0]["objectives"][0]
        first["requires"] = ["main_deliver"]
        with self.assertRaisesRegex(ValueError, "cyclic"):
            validate_plan(plan, world)
        plan = generate_quests(1, world, "easy")
        plan["quests"][0]["objectives"][1]["target_id"] = "nonexistent"
        with self.assertRaises(ValueError):
            validate_plan(plan, world)


class QuestProgressTests(unittest.TestCase):
    def test_early_dragon_defeat_and_wizard_visit_do_not_softlock_main(self):
        plan = generate_quests(3, world_fixture(), "easy")
        state = initial_state()
        self.assertFalse(required_complete(plan, state))
        self.assertEqual(eligible_objectives(plan, state, event_for(plan, "main_relic")), [])
        # The dragon and wizard are reachable even before accepting the quest.
        for oid in ("main_dragon", "main_ward"):
            state, emitted = advance(plan, state, event_for(plan, oid))
            self.assertEqual(emitted, [])
        self.assertNotIn("main_dragon", state["completed_objectives"])
        state, _ = advance(plan, state, event_for(plan, "main_accept"))
        self.assertTrue({"main_accept", "main_ward", "main_dragon"} <= set(state["completed_objectives"]))
        self.assertEqual(eligible_objectives(plan, state, event_for(plan, "main_relic")), ["main_relic"])
        state, _ = advance(plan, state, event_for(plan, "main_relic"))
        state, emitted = advance(plan, state, event_for(plan, "main_deliver"))
        self.assertIn("main", state["completed_quests"])
        self.assertTrue(required_complete(plan, state))
        self.assertEqual([event["quest_id"] for event in emitted], ["main"])
        state, emitted = advance(plan, state, event_for(plan, "main_deliver"))
        self.assertEqual(emitted, [])

    def test_hard_main_requires_scout_and_revisiting_wizard(self):
        plan = generate_quests(4, world_fixture(), "hard")
        state = initial_state()
        state, _ = advance(plan, state, event_for(plan, "main_accept"))
        state, _ = advance(plan, state, event_for(plan, "main_ward"))
        self.assertNotIn("main_ward", state["completed_objectives"])
        for oid in ("scout_accept", "scout_collect", "scout_deliver"):
            state, emitted = advance(plan, state, event_for(plan, oid))
        self.assertEqual(emitted[0]["quest_id"], "scout")
        self.assertEqual(emitted[0]["rewards"]["items"], ["scout_seal"])
        self.assertNotIn("main_ward", state["completed_objectives"])
        state, _ = advance(plan, state, event_for(plan, "main_ward"))
        state, _ = advance(plan, state, event_for(plan, "main_dragon"))
        state, _ = advance(plan, state, event_for(plan, "main_relic"))
        state, emitted = advance(plan, state, event_for(plan, "main_deliver"))
        self.assertIn("main", state["completed_quests"])
        self.assertEqual(emitted[0]["quest_id"], "main")

    def test_unconfirmed_early_search_cannot_be_banked_and_rewards_once(self):
        plan = generate_quests(5, world_fixture(), "easy")
        state = initial_state()
        state, _ = advance(plan, state, event_for(plan, "herb_collect"))
        self.assertNotIn("herb_collect", state["completed_objectives"])
        for oid in ("herb_accept", "herb_collect", "herb_deliver"):
            old_state = deepcopy(state)
            state, emitted = advance(plan, state, event_for(plan, oid))
            self.assertNotEqual(state, old_state)
        self.assertEqual(emitted, [{"type": "quest_completed", "quest_id": "herb",
                                    "rewards": {"potions": 2, "items": []}}])
        state, emitted = advance(plan, state, event_for(plan, "herb_deliver"))
        self.assertEqual(emitted, [])


if __name__ == "__main__":
    unittest.main()
