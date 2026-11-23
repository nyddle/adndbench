"""Reproduce a non-LLM smoke test of three expedition difficulty profiles.

Run from the repository root:
    PYTHONPATH=. python experiments/expedition_baseline_check.py

The baseline is a hand-written observation-only heuristic; it is not an LLM
and its results are not evidence of language-model capability. The public seed
range is exploratory and is not suitable as a hidden evaluation set.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter

from benchmark.expedition import ENGINE_VERSION, Game
from benchmark.expedition_baseline import ExpeditionBaselineAgent
from benchmark.runner import run_episode


def measure(level: str) -> dict:
    config = {
        "map_size": 6,
        "map_topology": "mixed",
        "terrain_diversity": 2,
        "quest_difficulty": level,
        "combat_difficulty": level,
        "npc_difficulty": level,
        "character_class": "generalist",
        "enemy_count": None,
    }
    rows = []
    for seed in range(30):
        episode = run_episode(seed, ExpeditionBaselineAgent(), max_turns=600,
                              scenario="expedition", scenario_config=config, probes=False)
        result = episode["result"]
        if (result["engine_version"] != ENGINE_VERSION or result["config"] != config
                or result["seed"] != str(seed)):
            raise RuntimeError("Episode seed, version or configuration does not match the experiment")
        if result["terminal_reason"] not in {"completed", "death", "turn_limit"}:
            raise RuntimeError("Episode did not terminate with a recognized outcome")
        rows.append(result)
    terminal_counts = Counter(row["terminal_reason"] for row in rows)
    winners = [row for row in rows if row["terminal_reason"] == "completed"]
    return {
        "config": config,
        "runs": len(rows),
        "terminal_counts": {reason: terminal_counts[reason] for reason in ("completed", "death", "turn_limit")},
        "median_turns_all": statistics.median(row["turns"] for row in rows),
        "median_turns_completed": statistics.median(row["turns"] for row in winners) if winners else None,
        "invalid_actions_total": sum(row["invalid_actions"] for row in rows),
    }


def main() -> None:
    print(json.dumps({
        "scenario": "expedition",
        "engine_version": ENGINE_VERSION,
        "component_versions": Game(0).component_versions,
        "agent": "observation-only handcrafted baseline; not an LLM",
        "seeds": {"start_inclusive": 0, "end_inclusive": 29},
        "max_turns": 600,
        "profiles": {level: measure(level) for level in ("easy", "medium", "hard")},
        "note": "All three axes change together; this does not isolate individual difficulty effects.",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
