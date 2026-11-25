"""Rule-based reference levels for the caravan scenario on public dev seeds.

Following the shortcut-audit precedent: these are heuristic scores without any
model calls, bounding what is achievable without the target capabilities.
"Random opportunist" has neither a map nor a quest journal; the stock
BaselineAgent has a perfect external journal and map but no planning. Low
heuristic scores do not prove the absence of other shortcuts.
"""
from __future__ import annotations

import json

from benchmark.caravan import DIRECTIONS, Game, _Random
from benchmark.runner import BaselineAgent

SEEDS = range(1, 21)


class RandomOpportunist:
    """Random valid moves; talks, searches and fights when possible. No memory."""

    def __init__(self, seed: int):
        self.rng = _Random(f"caravan-audit:{seed}")

    def act(self, obs):
        if obs.get("enemy"):
            return {"type": "attack"}
        if obs.get("npc") and self.rng.below(2) == 0:
            return {"type": "talk"}
        if self.rng.below(3) == 0:
            return {"type": "search"}
        exits = obs.get("exits") or list(DIRECTIONS)
        return {"type": "move", "direction": exits[self.rng.below(len(exits))]}


def run(agent_factory):
    per_seed = []
    for seed in SEEDS:
        game = Game(seed)
        agent = agent_factory(seed)
        obs = game.observe()
        while not obs["done"]:
            obs = game.step(agent.act(obs))
        result = game.result()
        per_seed.append({"seed": seed, "terminal_reason": result["terminal_reason"],
                         "quests_completed": result["quests_completed"],
                         "rooms_visited": result["rooms_visited"],
                         "invalid_actions": result["invalid_actions"],
                         "turns": result["turns"], "max_turns": game.max_turns})
    quests = [r["quests_completed"] for r in per_seed]
    return {"per_seed": per_seed,
            "quests_completed_mean": round(sum(quests) / len(quests), 2),
            "completed_seeds": sum(r["terminal_reason"] == "completed" for r in per_seed)}


def main():
    report = {
        "note": ("Dev-seed rule-based references for caravan-0.2.0; no model calls. "
                 "Low heuristic scores do not prove the absence of other shortcuts."),
        "seeds": list(SEEDS),
        "random_opportunist": run(lambda seed: RandomOpportunist(seed)),
        "baseline_agent": run(lambda seed: BaselineAgent()),
    }
    with open("experiments/caravan_audit.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    for name in ("random_opportunist", "baseline_agent"):
        data = report[name]
        print(f"{name}: квестов в среднем {data['quests_completed_mean']}/10, "
              f"полных прохождений {data['completed_seeds']}/{len(report['seeds'])}")


if __name__ == "__main__":
    main()
