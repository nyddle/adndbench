"""Local, public development-seed control: no LLM, HTTP or private data.

Run from adndbench-final: python3 experiments/quest_chain_calibration.py
"""
from collections import Counter
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from benchmark.quest_chains import LEVELS, VERSION, QuestChain, oracle, source_fingerprint


def episode(seed, level, strategy):
    env = QuestChain(seed, level, max_turns=24)
    optimal = oracle(env.plan) if strategy == 'oracle' else None
    for turn in range(env.max_turns):
        observation = env.observe()
        if optimal is not None:
            action = optimal[turn]
        else:
            done = set(observation['completed'])
            candidate = next(t for t in observation['tasks'] if t['id'] not in done
                             and set(t['requires']) <= done)
            action = {'type': candidate['type'], 'target': candidate['target']}
        env.step(action)
        if env.terminal_reason is not None:
            break
    return env.result()


def main():
    # Published dev seeds cannot serve as a held-out evaluation set.
    seeds = range(200)
    groups = []
    for level in LEVELS:
        for strategy in ('oracle', 'first_eligible'):
            rows = [episode(seed, level, strategy) for seed in seeds]
            successes = [r for r in rows if r['terminal_reason'] == 'completed']
            groups.append({'level': level, 'strategy': strategy, 'worlds': len(rows),
                'completed': len(successes),
                'optimal': sum(r['extra_turns'] == 0 for r in successes),
                'extra_turns': dict(sorted(Counter(r['extra_turns'] for r in successes).items())),
                'invalid_actions': sum(r['invalid_actions'] for r in rows),
                'oracle_min_turns': sorted(set(r['oracle_min_turns'] for r in rows))})
    print(json.dumps({'version': VERSION, 'source_sha256': source_fingerprint(),
                      'development_seed_description': 'integers 0..199',
                      'max_turns': 24, 'groups': groups,
                      'note': 'Development environment controls, not LLM accuracy or a hidden evaluation.'},
                     ensure_ascii=False, indent=2))

if __name__ == '__main__': main()
