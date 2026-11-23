"""Privileged-map controls for integrated development adventure, no API calls."""
from collections import Counter
import json
from benchmark.radical_adventure import Game,shortest_directions,source_fingerprint,VERSION
from benchmark.quest_trial import oracle,LEVELS
from benchmark.party_combat import shortest_victory


def play(seed, level, policy):
    game=Game(seed,memory='medium',navigation='hard',quests=level,combat='medium',party=False)
    game.step({'type':'talk'})
    solution=iter(oracle(game.quest)['actions']) if policy=='oracle' else None
    while not game.done:
        if solution is not None: action=next(solution)
        else:
            obs=game.observe(); done,items=set(obs['completed']),set(obs['inventory'])
            options=[t for t in obs['tasks'] if t['id'] not in done and set(t['requires'])<=done and set(t['consumes'])<=items]
            if not options:
                game.step({'type':'invalid'});continue
            action={'type':'perform','target':options[0]['id']}
        for d in shortest_directions(game.edges,game.position,game.task_rooms[action['target']]):
            if game.done:break
            game.step({'type':'move','direction':d})
        if game.done:break
        if action['target']==game.quest.plan['goal']:
            game.step({'type':'unlock','code':'-'.join(game.code)})
            if game.battle:
                fight=shortest_victory(game.battle)
                if fight['status']!='solved':raise RuntimeError('control encounter is not solvable')
                for attack in fight['actions']:
                    if not game.done:game.step(attack)
        if not game.done:game.step(action)
    return game.result()


def main():
    groups=[]
    for level in LEVELS:
        for policy in ('oracle','first_eligible'):
            rows=[play('radical-adventure-dev-'+str(i),level,policy) for i in range(100)]
            outcomes=Counter(r['terminal_reason'] for r in rows)
            groups.append({'level':level,'policy':policy,'worlds':len(rows),'outcomes':dict(outcomes),
                           'max_turns':max(r['turns'] for r in rows),
                           'invalid_actions':sum(r['invalid_actions'] for r in rows)})
    print(json.dumps({'protocol':VERSION,'source_sha256':source_fingerprint(),
        'worlds_per_group':100,'seed_set':'public radical-adventure-dev-0..99',
        'settings':{'memory':'medium','navigation':'hard','combat':'medium','party':False,'max_turns':300},
        'note':'Local privileged map/code controls. Not LLM results. Different levels generate different worlds.',
        'groups':groups},ensure_ascii=False,sort_keys=True,indent=2))

if __name__=='__main__':main()
