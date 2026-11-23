"""Privileged fixed-policy diagnostic, not LLM performance."""
from collections import Counter, deque
import json
import statistics
import time
from benchmark.adventure_party import Game, source_fingerprint
from benchmark.adventure_vectors import shortest_directions
from benchmark.party_combat import shortest_victory


def path_avoid(game,dest):
    queue=deque([(game.game.position,[])]); seen={game.game.position}
    while queue:
        p,path=queue.popleft()
        if p==dest:return path
        for d,q in game.game.edges[p].items():
            if q != game.game.lock and q not in seen:
                seen.add(q);queue.append((q,path+[d]))
    raise RuntimeError('candidate unreachable before lock')


def fight(game, policy):
    if not game.battle or game.battle.status != 'ongoing':return
    if policy=='recruit_oracle':
        result=shortest_victory(game.battle)
        if result['status']!='solved':raise RuntimeError('encounter not solved')
        for action in result['actions']:game.step(action)
    else:
        while not game.done and game.battle.status == 'ongoing':
            enemy=next(e for e in game.battle.enemies if e['hp'] > 0)
            game.step({'type':'strike','actor':'hero','target':enemy['id']})


def go(game,destination,policy):
    while not game.done and game.game.position!=destination:
        fight(game,policy)
        if game.done:break
        direction=shortest_directions(game.game.edges,game.game.position,destination)[0]
        game.step({'type':'move','direction':direction})
    fight(game,policy)


def play(seed,difficulty,policy):
    game=Game(seed,memory='medium',navigation='hard',quests='medium',combat_difficulty=difficulty)
    clue=game.step({'type':'talk'})['notice']['runes']
    if policy=='recruit_oracle':
        mage=next(pos for pos,roles in game.candidates.items() if 'mage' in roles)
        for direction in path_avoid(game,mage):game.step({'type':'move','direction':direction})
        game.step({'type':'recruit','candidate':'mage'})
    for task in game.game.tasks:
        dest=next(pos for pos,name in game.game.names.items() if name==task['room'])
        go(game,dest,policy)
        if game.done:return game.result()
        game.step({'type':'interact','target':task['id']})
    go(game,game.game.lock,policy)
    if not game.done:game.step({'type':'unlock','code':'-'.join(clue)})
    if not game.done:go(game,game.game.home,policy)
    return game.result()


def main():
    start=time.perf_counter()
    out={'source_fingerprint':source_fingerprint(),'worlds_per_group':100,
      'seed_set':'public-party-adventure-dev-0..99',
      'note':'Both controls use a privileged map; one also knows candidate placement and uses the combat oracle. Not LLM results.',
      'groups':[]}
    for level in ('easy','medium','hard'):
        for policy in ('recruit_oracle','solo_strike'):
            begin=time.perf_counter()
            rows=[play(f'public-party-adventure-dev-{i}',level,policy) for i in range(100)]
            c=Counter(r['terminal_reason'] for r in rows)
            out['groups'].append({'difficulty':level,'policy':policy,'completed':c['completed'],
              'death':c['death'],'turn_limit':c['turn_limit'],'combat_limit':c['combat_limit'],
              'invalid_actions':sum(r['invalid_actions'] for r in rows),
              'median_turns':statistics.median(r['turns'] for r in rows),
              'elapsed_seconds':round(time.perf_counter()-begin,3)})
    out['elapsed_seconds']=round(time.perf_counter()-start,3)
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
