"""Play the integrated adventure with one JSON action per input line."""
import argparse
import json
from benchmark.adventure_party import Game, system_prompt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for axis in ('memory', 'navigation', 'quests'):
        parser.add_argument('--'+axis, choices=('easy','medium','hard'), default='easy')
    parser.add_argument('--combat', choices=('off','easy','medium','hard'), default='easy')
    parser.add_argument('--party', choices=('on','off'), default='on')
    parser.add_argument('--seed', default='dev-example', help='Public development seed; not a private evaluation set.')
    args=parser.parse_args()
    has_party, has_combat = args.party == 'on', args.combat != 'off'
    game=Game(args.seed, memory=args.memory, navigation=args.navigation, quests=args.quests,
              party_enabled=has_party, combat_enabled=has_combat,
              combat_difficulty=args.combat if has_combat else 'easy')
    print(system_prompt(has_party, has_combat),flush=True)
    while not game.done:
        print(json.dumps(game.observe(),ensure_ascii=False),flush=True)
        try: raw=input()
        except EOFError:
            print('Episode interrupted; no terminal result.',flush=True)
            return
        try: action=json.loads(raw)
        except (TypeError, ValueError): action={'type':'invalid'}
        game.step(action)
    print(json.dumps({'observation':game.observe(),'result':game.result()},ensure_ascii=False),flush=True)

if __name__=='__main__': main()
