"""Manually play the integrated research adventure on a public development seed."""
import argparse
import json
from benchmark.radical_adventure import Game,SYSTEM_PROMPT


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seed',default='dev-example')
    p.add_argument('--memory',choices=('easy','medium','hard','extreme'),default='medium')
    p.add_argument('--navigation',choices=('easy','medium','hard'),default='medium')
    p.add_argument('--quests',choices=('medium','hard','extreme'),default='hard')
    p.add_argument('--combat',choices=('off','easy','medium','hard'),default='medium')
    p.add_argument('--party',choices=('on','off'),default='on')
    p.add_argument('--max-turns',type=int,default=300)
    a=p.parse_args()
    game=Game(a.seed,memory=a.memory,navigation=a.navigation,quests=a.quests,combat=a.combat,
              party=a.party=='on',max_turns=a.max_turns)
    print(SYSTEM_PROMPT,flush=True)
    while not game.done:
        print(json.dumps(game.observe(),ensure_ascii=False),flush=True)
        try: raw=input()
        except EOFError:
            print('Episode interrupted; no terminal result.',flush=True);return
        try:action=json.loads(raw)
        except (ValueError,TypeError):action={'type':'invalid'}
        game.step(action)
    print(json.dumps({'observation':game.observe(),'result':game.result()},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
