"""Offline development controls, not LLM benchmarking; public dev seeds."""
from collections import Counter
import json
import statistics
import time
from benchmark.memory_navigation import create_game, ITEMS, LEVELS, VERSION, source_fingerprint

N = 200
OPPOSITE = {'north':'south', 'east':'west', 'south':'north', 'west':'east'}


def memory_agent(game, mode):
    saved, latest = None, None
    while not game.done:
        o = game.observe()
        if 'encounter' in o:
            enc = o['encounter']
            latest = enc['request']
            if enc['main']: saved = enc['request']
            action = {'type': 'move', 'direction': 'forward'}
        else:
            action = {'type': 'answer', 'item': saved if mode == 'remember' else latest}
        game.step(action)
    return game.result()


def nav_agent(game, mode):
    tried, parents, previous, previous_direction = {}, {}, None, None
    while not game.done:
        o = game.observe(); room = o['room']
        if room not in tried:
            tried[room] = set()
            if previous is not None:
                parents[room] = OPPOSITE[previous_direction]
                tried[room].add(parents[room])
        if mode == 'map_dfs':
            options = [d for d in o['exits'] if d not in tried[room]]
            direction = options[0] if options else parents[room]
            tried[room].add(direction)
        else:
            direction = o['exits'][0]
        previous, previous_direction = room, direction
        game.step({'type':'move', 'direction':direction})
    return game.result()


def main():
    start = time.perf_counter()
    result = {'version': VERSION, 'fingerprint': source_fingerprint(),
              'agent_description': 'handwritten local controls, not LLMs',
              'worlds_per_group': N, 'public_development_seeds': 'dev-control-0 through dev-control-199',
              'groups': []}
    for vector, runner, agents in [('memory', memory_agent, ('remember','latest')),
                                    ('navigation', nav_agent, ('map_dfs','first_exit'))]:
        for level in LEVELS:
            for agent in agents:
                begin = time.perf_counter()
                rows = [runner(create_game(vector, f'dev-control-{i}', level), agent) for i in range(N)]
                reasons = Counter(r['terminal_reason'] for r in rows)
                result['groups'].append({'vector':vector, 'level':level, 'agent':agent,
                    'completed': reasons['completed'], 'incorrect_answer': reasons['incorrect_answer'],
                    'turn_limit': reasons['turn_limit'], 'invalid_actions':sum(r['invalid_actions'] for r in rows),
                    'median_turns_all': statistics.median(r['turns'] for r in rows),
                    'elapsed_seconds': round(time.perf_counter()-begin, 3)})
    result['elapsed_seconds'] = round(time.perf_counter()-start, 3)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__': main()
