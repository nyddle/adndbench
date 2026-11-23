"""Deterministic public dev controls, no API and no hidden evaluation worlds."""
from __future__ import annotations
from collections import deque
import json
import statistics
import time
from benchmark.hard_memory_navigation import LEVELS, create_game, source_fingerprint

DIRECTIONS=('north','east','south','west')
OPPOSITE={'north':'south','south':'north','east':'west','west':'east'}


class Recall:
    def __init__(self): self.holdings={}
    def act(self, obs):
        if 'assignments' in obs:
            self.holdings={r['person']:r['item'] for r in obs['assignments']}
        if 'event' in obs:
            a,b=obs['event']['people'];self.holdings[a],self.holdings[b]=self.holdings[b],self.holdings[a]
        if 'query' in obs:
            target=obs['query']['item'];person=next(k for k,v in self.holdings.items() if v==target)
            return {'type':'deliver','person':person}
        return {'type':'move','direction':'forward'}


class Guess:
    def act(self,obs):
        if 'query' in obs:return {'type':'deliver','person':obs['query']['candidates'][0]}
        return {'type':'move','direction':'forward'}


class MapExplorer:
    """Records only public observations and travels to a discovered frontier."""
    def __init__(self): self.graph={};self.exits={};self.previous=None
    def shortest(self,start,goal):
        q=deque([(start,[])]);visited={start}
        while q:
            node,path=q.popleft()
            if goal(node):return path
            for d,nxt in self.graph.get(node,{}).items():
                if nxt not in visited:visited.add(nxt);q.append((nxt,path+[d]))
        return None
    def act(self,obs):
        room=obs['room'];self.graph.setdefault(room,{});self.exits[room]=list(obs['exits'])
        if self.previous:
            prev,d=self.previous
            self.graph[prev][d]=room;self.graph[room][OPPOSITE[d]]=prev
            self.previous=None
        if room==obs['goal'] and not obs['relic']:return {'type':'search'}
        if obs['relic']:
            path=self.shortest(room,lambda x:x==obs['home'])
        else:
            path=self.shortest(room,lambda x:any(d not in self.graph[x] for d in self.exits[x]))
            if path == []:
                path=[next(d for d in self.exits[room] if d not in self.graph[room])]
        if not path:raise RuntimeError('no route or frontier')
        d=path[0];self.previous=(room,d);return {'type':'move','direction':d}


class FirstExit:
    def act(self,obs):
        if obs['room']==obs['goal'] and not obs['relic']:return {'type':'search'}
        return {'type':'move','direction':obs['exits'][0]}


def main():
    n=100;groups=[]
    for axis,policies in (('memory',(('recall',Recall),('first_person',Guess))),
                          ('navigation',(('map_explorer',MapExplorer),('first_exit',FirstExit)))):
        for level in LEVELS:
            for name,policy_class in policies:
                wins=invalid=turns=0; outcomes={};samples=[];started=time.monotonic()
                for i in range(n):
                    game=create_game(axis,f'hard-dev-{i}',level);policy=policy_class()
                    while not game.done: game.step(policy.act(game.observe()))
                    res=game.result();wins+=int(res['completed']);invalid+=res['invalid_actions'];turns+=res['turns'];samples.append(res['turns'])
                    reason=res['terminal_reason'];outcomes[reason]=outcomes.get(reason,0)+1
                groups.append({'axis':axis,'level':level,'control':name,'worlds':n,'completed':wins,
                               'outcomes':outcomes,'invalid_actions':invalid,'median_turns_all':statistics.median(samples),
                               'elapsed_seconds':round(time.monotonic()-started,3)})
    print(json.dumps({'version':'hard-memory-navigation-0.1.0','fingerprint':source_fingerprint(),
                      'world_set':'public-development-worlds-0..99','groups':groups,
                      'note':'No model calls. Observation-only controls; results do not establish LLM difficulty.'},
                     ensure_ascii=False,indent=2))

if __name__=='__main__':main()
