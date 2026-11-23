"""Reproducible non-LLM sanity-check on the existing 0.1.0 environment.
Run from the repository root: PYTHONPATH=. python experiments/compare_baselines.py
"""
import json, random, statistics
from collections import Counter
from benchmark.engine import Game, ENGINE_VERSION
from benchmark.runner import BaselineAgent

class RandomWalk:
    """Fight when needed, otherwise choose a move uniformly. No quests taken."""
    def __init__(self, seed): self.rng = random.Random(12491 + seed)
    def act(self, o):
        if o['enemy']:
            if o['hp'] <= 6 and o['potions']:
                return {'type': 'potion'}
            return {'type': 'attack'}
        return {'type': 'move', 'direction': self.rng.choice(o['exits'])}

class ReactiveWalk:
    """Random walk, talk when new inventory, search rooms after new NPCs.

    Stores local NPC visits and rooms searched; does not parse quests, build a
    map or plan routes. It may encounter quest targets and givers by chance.
    """
    def __init__(self, seed):
        self.rng = random.Random(12491 + seed)
        self.seen_npcs = set()
        self.talks = set()
        self.searches = set()
        self.refuge = None
    def act(self, o):
        room = o['room']
        if self.refuge is None: self.refuge = room
        if o['enemy']:
            if o['hp'] <= 6 and o['potions']:
                return {'type': 'potion'}
            return {'type': 'attack'}
        inv = tuple(sorted(o['inventory']))
        talk_key = (room, inv)
        if o['npc'] and talk_key not in self.talks:
            self.seen_npcs.add(room)
            self.talks.add(talk_key)
            return {'type': 'talk'}
        search_key = (room, len(self.seen_npcs))
        if search_key not in self.searches:
            self.searches.add(search_key)
            return {'type': 'search'}
        if room == self.refuge and o['hp'] <= 9 and o['rations']:
            return {'type': 'rest'}
        return {'type': 'move', 'direction': self.rng.choice(o['exits'])}

def trial(agent, seed):
    g = Game(seed, max_turns=120)
    o = g.observe()
    while not o['done']:
        o = g.step(agent.act(o))
    return g.result()

def measure(name, factory):
    rows = [trial(factory(seed), seed) for seed in range(1000)]
    total = len(rows)
    winners = [r for r in rows if r['terminal_reason'] == 'completed']
    return {'name': name, 'n': total,
      'completion_count': len(winners), 'completion_rate': len(winners) / total,
      'mean_quests': sum(r['quests_completed'] for r in rows)/total,
      'mean_coverage': sum(r['rooms_visited'] for r in rows)/total/16,
      'mean_turns': sum(r['turns'] for r in rows)/total,
      'median_turns_among_winners': statistics.median([r['turns'] for r in winners]) if winners else None,
      'mean_invalid_actions': sum(r['invalid_actions'] for r in rows)/total,
      'mean_damage': sum(r['damage_taken'] for r in rows)/total,
      'reasons': dict(Counter(r['terminal_reason'] for r in rows)),
      'quest_histogram': dict(Counter(r['quests_completed'] for r in rows))}

def main():
    result = {'engine_version': ENGINE_VERSION, 'seed_start': 0, 'seed_end_inclusive': 999,
              'max_turns': 120,
              'agents': [measure('random_walk', RandomWalk),
                         measure('reactive_random_walk', ReactiveWalk),
                         measure('provided_rule_baseline', lambda seed: BaselineAgent())]}
    print(json.dumps(result, indent=2, ensure_ascii=False))
if __name__ == '__main__': main()
