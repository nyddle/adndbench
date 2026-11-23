"""Paired one-axis-at-a-time smoke test using an observation-only heuristic.

This is NOT an LLM evaluation. Public exploratory seeds are not a hidden set.
Run: PYTHONPATH=. python experiments/calibration_pilot/baseline_axes.py
"""
import json
import statistics
from collections import Counter
from benchmark.expedition import Game, ENGINE_VERSION
from benchmark.expedition_baseline import ExpeditionBaselineAgent
from benchmark.runner import run_episode

BASE = {'map_size': 6, 'map_topology': 'mixed', 'terrain_diversity': 2,
        'quest_difficulty': 'easy', 'combat_difficulty': 'easy', 'npc_difficulty': 'easy',
        'character_class': 'generalist', 'enemy_count': 2}
VARIANTS = {
    'control': {},
    'quests_hard': {'quest_difficulty': 'hard'},
    'combat_hard': {'combat_difficulty': 'hard'},
    'six_enemies': {'enemy_count': 6},
    'npc_hard': {'npc_difficulty': 'hard'},
    'map_8': {'map_size': 8},
    'class_warrior': {'character_class': 'warrior'},
}

def main():
    output = {'engine_version': ENGINE_VERSION, 'component_versions': Game(0).component_versions,
              'agent': 'observation-only handcrafted heuristic; not an LLM',
              'seeds': list(range(30)), 'max_turns': 600, 'variants': {}}
    for name, change in VARIANTS.items():
        config = {**BASE, **change}
        rows = [run_episode(seed, ExpeditionBaselineAgent(), scenario='expedition',
                            scenario_config=config, max_turns=600, probes=False)['result']
                for seed in output['seeds']]
        reasons = Counter(r['terminal_reason'] for r in rows)
        output['variants'][name] = {
            'config': config, 'runs': len(rows),
            'outcomes': {x: reasons[x] for x in ('completed', 'death', 'turn_limit')},
            'median_turns_all': statistics.median(r['turns'] for r in rows),
            'invalid_actions_total': sum(r['invalid_actions'] for r in rows),
            'per_seed': [{'seed': r['seed'], 'reason': r['terminal_reason'], 'turns': r['turns'],
                          'main_completed': r['main_quest_completed']} for r in rows],
        }
    print(json.dumps(output, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
