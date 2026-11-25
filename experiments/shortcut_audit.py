"""Shortcut-heuristic audit for the experimental memory-updates episode and
route probes, on public development seeds only.

Following the fixed-probes-v3 audit precedent: low heuristic accuracy is
necessary but not sufficient; unmeasured shortcuts may remain. These are
rule-based guesses on dev seeds, not model results and not an evaluation set.
"""
from __future__ import annotations

from collections import Counter
import json
import re

from benchmark.memory_updates import create_game, LEVELS
from benchmark.route_probes import build_route_probes
from benchmark.runner import run_episode, BaselineAgent

MEMORY_SEEDS = 200
ROUTE_SEEDS = {'classic': 200, 'realms': 200, 'expedition': 100}
_PAIR = re.compile(r'комнаты «(.+?)» и «(.+?)»')


def audit_memory_updates():
    """Accuracy of naive answering strategies per level."""
    report = {}
    for level in LEVELS:
        hits = Counter()
        for seed in range(MEMORY_SEEDS):
            game = create_game(seed, level)
            answer, choices, records = game.answer, game.choices, game.records
            # First value mentioned in the main request.
            hits['first_main_value'] += int(records[0]['item'] == answer)
            # Item mentioned in the most recent encounter of any person.
            hits['last_mentioned_item'] += int(records[-1]['item'] == answer)
            # Most frequently mentioned item; ties broken by first occurrence.
            counts = Counter(rec['item'] for rec in records)
            guess = max(counts, key=lambda item: (counts[item],
                                                  -next(i for i, rec in enumerate(records)
                                                        if rec['item'] == item)))
            hits['most_frequent_item'] += int(guess == answer)
            hits['_expected_random'] += 1 / len(choices)
            hits['_episodes'] += 1
        episodes = hits.pop('_episodes')
        expected_random = hits.pop('_expected_random') / episodes
        report[level] = {
            'episodes': episodes,
            'expected_random_accuracy': round(expected_random, 4),
            **{name: {'correct': hits[name], 'accuracy': round(hits[name] / episodes, 4)}
               for name in ('first_main_value', 'last_mentioned_item', 'most_frequent_item')},
        }
    return report


def _exits_when_first_seen(trace, room):
    for turn in trace:
        obs = turn.get('observation', {})
        if obs.get('room') == room:
            return list(obs.get('exits', []))
    return None


def evaluate(hits, trace, probes, suffix):
    last_move = next((t['action'].get('direction') for t in reversed(trace)
                      if isinstance(t.get('action'), dict)
                      and t['action'].get('type') == 'move'), None)
    for probe in probes:
        match = _PAIR.search(probe['question'])
        if not match:
            continue
        start, _destination = match.groups()
        exits = _exits_when_first_seen(trace, start)
        hits[f'_probes_{suffix}'] += 1
        if exits:
            hits[f'first_listed_exit_{suffix}'] += int(exits[0] == probe['answer'])
            hits[f'_expected_random_{suffix}'] += 1 / len(exits)
        if last_move is not None:
            hits[f'last_move_direction_{suffix}'] += int(last_move == probe['answer'])


def audit_route_probes():
    """Accuracy of naive first-exit strategies on baseline-agent traces."""
    report = {}
    for scenario, seeds in ROUTE_SEEDS.items():
        hits = Counter()
        for seed in range(seeds):
            if scenario == 'classic':
                agent = BaselineAgent()
            elif scenario == 'realms':
                from benchmark.realms_baseline import RealmsBaselineAgent
                agent = RealmsBaselineAgent()
            else:
                from benchmark.expedition_baseline import ExpeditionBaselineAgent
                agent = ExpeditionBaselineAgent()
            episode = run_episode(seed, agent, scenario=scenario, probes=False)
            for min_exits in (1, 3):
                probes = build_route_probes(episode['trace'], episode['final_observation'],
                                            min_exits=min_exits)
                evaluate(hits, episode['trace'], probes, f'min_exits_{min_exits}')
        scenario_report = {'seeds': seeds}
        for suffix in ('min_exits_1', 'min_exits_3'):
            total = hits.pop(f'_probes_{suffix}')
            expected_random = hits.pop(f'_expected_random_{suffix}') / total if total else None
            scenario_report[suffix] = {
                'probes': total,
                'expected_random_accuracy': round(expected_random, 4) if expected_random else None,
                **{name: {'correct': hits[f'{name}_{suffix}'],
                          'accuracy': round(hits[f'{name}_{suffix}'] / total, 4) if total else None}
                   for name in ('first_listed_exit', 'last_move_direction')},
            }
        report[scenario] = scenario_report
    return report


def main():
    report = {
        'note': ('Dev-seed shortcut audit; public seeds, no model calls. Low heuristic '
                 'accuracy does not prove absence of other shortcuts.'),
        'memory_updates': audit_memory_updates(),
        'route_probes': audit_route_probes(),
    }
    with open('experiments/shortcut_audit.json', 'w', encoding='utf-8') as f:
        f.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
