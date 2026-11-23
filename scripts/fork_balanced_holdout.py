#!/usr/bin/env python3
"""Fork a completed balanced-memory dev study into fresh holdout worlds, offline.

Run seal and holdout through three_model_balanced_memory.py after inspecting the
private audit. This script never calls a model or changes the source study.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts import three_model_balanced_memory as wrapper
engine = wrapper.engine


def fork(source, destination, *, holdout_worlds=3, max_calls=75, max_input_tokens=1500000):
    if source == destination:
        raise ValueError('source and destination must differ')
    wrapper.configure_existing(source)
    source_dir = engine.path_for(source)
    destination_dir = engine.path_for(destination)
    # Existing lock only: do not create or change any source study file.
    fd = os.open(source_dir / '.lock', os.O_RDWR)
    with os.fdopen(fd, 'r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _, plan, state = engine.load(source)
        if (plan['adapter'] != wrapper.ADAPTER or plan['axis'] != wrapper.AXIS
                or plan['level'] != 's4'):
            raise ValueError('expected balanced s4 study')
        if not (1 <= holdout_worlds <= 10 and max_calls <= 1000
                and max_input_tokens <= 20000000
                and max_calls > plan['max_calls_per_split']
                and max_input_tokens >= plan['max_input_tokens_per_split']
                and max_calls >= holdout_worlds * len(wrapper.MODELS) * 4):
            raise ValueError('invalid technical budget')
        if state['receipts']['holdout'] or any(k.startswith('holdout:') for k in state['episodes']):
            raise ValueError('source holdout already accessed')
        expected = {engine.key_for('dev', world, model): seed
                    for world, seed, model in engine.specs(plan, 'dev')}
        if set(state['episodes']) != set(expected):
            raise ValueError('dev episodes incomplete or unexpected')
        receipts = state['receipts']['dev']
        if any(r.get('status') != 'completed' or r.get('episode') not in expected for r in receipts):
            raise ValueError('unresolved or unexpected dev receipt')
        for key, seed in expected.items():
            record = state['episodes'][key]
            if record.get('status') != 'completed':
                raise ValueError('dev episode incomplete')
            if sum(r['episode'] == key for r in receipts) != len(record['turns']):
                raise ValueError('dev receipts and actions differ')
            engine.reconstruct(plan, seed, record)
        used = set(plan['seeds']['dev'] + plan['seeds']['holdout'])
        fresh = []
        while len(fresh) < holdout_worlds:
            seed = secrets.token_hex(16)
            if seed not in used:
                fresh.append(seed)
                used.add(seed)
        new_plan = copy.deepcopy(plan)
        new_plan['seeds']['holdout'] = fresh
        new_plan['max_calls_per_split'] = max_calls
        new_plan['max_input_tokens_per_split'] = max_input_tokens
        old_budget = {'max_calls_per_split': plan['max_calls_per_split'],
                      'max_input_tokens_per_split': plan['max_input_tokens_per_split']}
        new_budget = {'max_calls_per_split': max_calls, 'max_input_tokens_per_split': max_input_tokens}
        provenance = {'version': 'fresh-holdout-fork-1', 'source_name': source,
                      'source_plan_sha256': engine.digest(plan), 'source_state_sha256': engine.digest(state),
                      'source_fingerprint': plan['source_sha256'], 'old_budget': old_budget,
                      'new_budget': new_budget, 'fresh_holdout_worlds': holdout_worlds,
                      'fork_tool_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        new_plan['fork_provenance'] = provenance
        new_state = {'sealed': False, 'plan_sha256': engine.digest(new_plan),
                     'episodes': copy.deepcopy(state['episodes']),
                     'receipts': {'dev': copy.deepcopy(receipts), 'holdout': []}}
        for key, seed in expected.items():
            engine.reconstruct(new_plan, seed, new_state['episodes'][key])
        audit = {**provenance, 'destination_name': destination,
                 'created_utc': datetime.now(timezone.utc).isoformat(),
                 'new_plan_sha256': engine.digest(new_plan), 'new_state_sha256': engine.digest(new_state),
                 'selection': 'fresh random seeds disjoint from both source pools',
                 'note': 'Dev outcomes are copied and replay-validated; no holdout game was observed.'}
        # Exclusive creation prevents overwriting an existing plan. Audit comes first;
        # the runner cannot load a partially written plan until state is present.
        destination_dir.mkdir(mode=0o700, exist_ok=False)
        engine.write(destination_dir / 'audit.json', audit)
        engine.write(destination_dir / 'plan.json', new_plan)
        engine.write(destination_dir / 'state.json', new_state)
    print(f'Created private fork {destination}: {len(plan["seeds"]["dev"])} replayed dev worlds, '
          f'{holdout_worlds} fresh holdout worlds; no model calls. Calls/split: {max_calls}.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source'); parser.add_argument('destination')
    parser.add_argument('--holdout-worlds', type=int, default=3)
    parser.add_argument('--max-calls', type=int, default=75)
    parser.add_argument('--max-input-tokens', type=int, default=1500000)
    args = parser.parse_args()
    fork(args.source, args.destination, holdout_worlds=args.holdout_worlds,
         max_calls=args.max_calls, max_input_tokens=args.max_input_tokens)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'Fork stopped: {exc}. No model calls.', file=sys.stderr)
        sys.exit(1)
