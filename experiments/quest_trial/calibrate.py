"""Reproducible research controls; never use these public seeds as holdout.

Run: python3 -m experiments.quest_trial.calibrate
"""
from collections import Counter
import json
from benchmark.quest_trial import LEVELS, QuestTrial, oracle, source_fingerprint, VERSION


def play(seed,level,policy):
    game=QuestTrial(f'quest-trial-dev-{seed}',level)
    if policy=='oracle':
        proof=oracle(game)
        if proof['status']!='solved':raise RuntimeError('oracle did not solve')
        actions=iter(proof['actions'])
    while not game.done:
        obs=game.observe()
        if policy=='oracle':action=next(actions)
        else:
            done,items=set(obs['completed']),set(obs['inventory'])
            candidates=[t for t in obs['tasks'] if t['id'] not in done and set(t['requires'])<=done and set(t['consumes'])<=items]
            action={'type':'perform','target':candidates[0]['id']} if candidates else {'type':'invalid'}
        game.step(action)
    return game.result()


def main():
    groups=[]
    for level in LEVELS:
        for policy in ('oracle','first_eligible'):
            results=[play(i,level,policy) for i in range(200)]
            counts=Counter(r['terminal_reason'] for r in results)
            groups.append({'level':level,'policy':policy,'worlds':len(results),
                           'completed':counts['completed'],'turn_limit':counts['turn_limit'],
                           'invalid_actions':sum(r['invalid_actions'] for r in results),
                           'oracle_min_turns':results[0]['oracle_min_turns'],
                           'max_turns':results[0]['max_turns']})
    print(json.dumps({'protocol':VERSION,'source_sha256':source_fingerprint(),
                      'worlds_per_group':200,'seed_set':'public quest-trial-dev-0..199',
                      'note':'Local development controls, not an evaluation of models.',
                      'groups':groups},ensure_ascii=False,sort_keys=True,indent=2))

if __name__=='__main__':main()
