"""Offline controls over public development worlds; no LLM/provider calls."""
from collections import Counter, deque
import json
import statistics
import time
from benchmark.adventure_vectors import Game, LEVELS, source_fingerprint

OPPOSITE={'north':'south','south':'north','east':'west','west':'east'}


def known_path(graph, start, goal):
    todo=deque([(start,[])]); seen={start}
    while todo:
        room,path=todo.popleft()
        if room == goal: return path
        for d,nxt in graph.get(room,{}).items():
            if nxt not in seen:
                seen.add(nxt); todo.append((nxt,path+[d]))
    return None


def play(seed, config, strategy):
    g=Game(seed, **config)
    graph, exits = {}, {}
    prior_room=prior_dir=None
    code=None
    while not g.done:
        obs=g.observe(); room=obs['room']
        graph.setdefault(room,{})
        exits[room]=obs['exits']
        if prior_room is not None:
            graph[prior_room][prior_dir]=room
            graph[room][OPPOSITE[prior_dir]]=prior_room
            prior_room=prior_dir=None
        if 'runes' in obs['notice']:
            code='-'.join(obs['notice']['runes'])
        if not obs['briefed']:
            action={'type':'talk'}
        else:
            remaining=[t for t in obs['tasks'] if t['id'] not in obs['completed_tasks']]
            if remaining:
                if strategy == 'goal_first': task=remaining[-1]
                else: task=next(t for t in remaining if set(t['requires']) <= set(obs['completed_tasks']))
                target=task['room']
                action={'type':'interact','target':task['id']} if room == target else None
            elif not obs['relic']:
                target=obs['lock_room']
                action={'type':'unlock','code': ('-'.join(['sun'] * {'easy':1,'medium':2,'hard':3}[config['memory']]) if strategy=='guess_code' else code)} if room == target else None
            else:
                target=obs['home']
                action=None
            if action is None:
                if strategy == 'first_exit':
                    direction=obs['exits'][0]
                else:
                    path=known_path(graph,room,target)
                    if path:
                        direction=path[0]
                    else:
                        # Nearest known room with an unexplored exit.
                        frontier=[]
                        for r in graph:
                            unknown=[d for d in exits.get(r,[]) if d not in graph[r]]
                            route=known_path(graph,room,r)
                            if unknown and route is not None:
                                frontier.append((len(route),r,route,unknown))
                        if not frontier: raise RuntimeError('no frontier and target not reached')
                        _,_,route,unknown=min(frontier,key=lambda x:(x[0],x[1]))
                        direction=route[0] if route else unknown[0]
                action={'type':'move','direction':direction}
                prior_room,prior_dir=room,direction
        g.step(action)
    return g.result()


def main():
    started=time.perf_counter(); output={'fingerprint':source_fingerprint(),
      'seed_set':'public-adventure-dev-0..99', 'worlds_per_group':100, 'groups':[]}
    for axis,weak in [('memory','guess_code'),('navigation','first_exit'),('quests','goal_first')]:
        for level in LEVELS:
            config={'memory':'easy','navigation':'easy','quests':'easy'};config[axis]=level
            for strategy in ('map_and_recall',weak):
                begin=time.perf_counter()
                rows=[play(f'public-adventure-dev-{i}',config,strategy) for i in range(100)]
                result=Counter(r['terminal_reason'] for r in rows)
                output['groups'].append({'axis':axis,'level':level,'strategy':strategy,
                  'completed':result['completed'],'incorrect_code':result['incorrect_code'],
                  'turn_limit':result['turn_limit'],'invalid_actions':sum(r['invalid_actions'] for r in rows),
                  'median_turns_all':statistics.median(r['turns'] for r in rows),
                  'elapsed_seconds':round(time.perf_counter()-begin,3)})
    output['elapsed_seconds']=round(time.perf_counter()-started,3)
    print(json.dumps(output,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
