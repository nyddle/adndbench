"""Play a development episode with one JSON action per line on stdin."""
import argparse
import json
from benchmark.vector_scenarios import SCENARIOS, LEVELS, create_game, system_prompt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--axis', required=True, choices=SCENARIOS)
    parser.add_argument('--level', required=True, choices=LEVELS)
    parser.add_argument('--seed', default='dev-example', help='Use only public development seeds in this CLI.')
    args = parser.parse_args()
    game = create_game(args.axis, args.seed, args.level)
    print(system_prompt(args.axis), flush=True)
    obs = game.observe()
    while not obs.get('done') and obs.get('terminal_reason') is None:
        print(json.dumps(obs, ensure_ascii=False), flush=True)
        try:
            raw = input()
        except EOFError:
            print('Episode interrupted; no terminal result.', flush=True)
            return
        try: action = json.loads(raw)
        except (TypeError, ValueError): action = {'type': 'invalid'}
        obs = game.step(action)
    print(json.dumps({'observation': obs, 'result': game.result()}, ensure_ascii=False), flush=True)

if __name__ == '__main__': main()
