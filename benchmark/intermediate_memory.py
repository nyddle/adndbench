"""A standalone six-turn midpoint between the base and hard memory pilots.

All exchanges are visible, in order, grouped into blocks of at most six. This
is exploratory calibration, not an established 50-percent difficulty setting.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
from benchmark.fixed_probes import _Stream
from benchmark.hard_memory_navigation import ITEMS, COMPACT_MEMORY_PROMPT

VERSION='intermediate-memory-0.1.0'
LEVELS=('medium',)
SYSTEM_PROMPT=COMPACT_MEMORY_PROMPT
PEOPLE_COUNT=8
EVENT_COUNT=24
MIN_TARGET_MOVES=4
GROUP_SIZE=6


def source_fingerprint():
    h=hashlib.sha256()
    for p in (Path(__file__),Path(__file__).with_name('hard_memory_navigation.py'),
              Path(__file__).with_name('fixed_probes.py')):
        h.update(p.name.encode()+b'\0'+p.read_bytes()+b'\0')
    return h.hexdigest()


class Game:
    def __init__(self,seed:str|int):
        if isinstance(seed,bool) or not isinstance(seed,(str,int)):
            raise ValueError('seed must be a string or integer')
        rng=_Stream(str(seed),VERSION)
        people=[f'житель-{i:02d}' for i in range(1,PEOPLE_COUNT+1)]
        items=list(ITEMS);rng.shuffle(items);items=items[:PEOPLE_COUNT];rng.shuffle(people)
        initial=dict(zip(people,items))
        for _ in range(5000):
            target=items[rng.below(PEOPLE_COUNT)]
            holdings=dict(initial);events=[];touches=0
            initial_owner=next(p for p in people if holdings[p]==target)
            for _ in range(EVENT_COUNT):
                a=people[rng.below(PEOPLE_COUNT)]
                others=[p for p in people if p!=a];b=others[rng.below(len(others))]
                last_touch=target in (holdings[a],holdings[b]);touches+=int(last_touch)
                events.append({'people':[a,b]});holdings[a],holdings[b]=holdings[b],holdings[a]
            final_owner=next(p for p in people if holdings[p]==target)
            if touches>=MIN_TARGET_MOVES and not last_touch and final_owner!=initial_owner:
                break
        else:raise RuntimeError('could not construct memory episode')
        assignments=[{'person':p,'item':initial[p]} for p in people];rng.shuffle(assignments)
        self.seed=str(seed);self.initial=assignments;self.events=events;self.target=target;self.answer=final_owner
        self.people=sorted(people);self.offset=-1;self.turn=0;self.max_turns=10
        self.invalid_actions=0;self.done=False;self.terminal_reason=None;self.message='Начало путешествия.'
        self.config={'axis':'memory-compact','level':'medium','people':PEOPLE_COUNT,'exchanges':EVENT_COUNT,
                     'group_size':GROUP_SIZE,'min_target_moves':MIN_TARGET_MOVES}

    def observe(self):
        out={'version':VERSION,'axis':'memory-compact','turn':self.turn,'max_turns':self.max_turns,
             'done':self.done,'message':self.message}
        if self.offset==-1:
            out.update(location='лагерь',assignments=deepcopy(self.initial),exits=['forward'])
        elif self.offset<len(self.events):
            out.update(location='стоянка',events=deepcopy(self.events[self.offset:self.offset+GROUP_SIZE]),
                       rules='Обмены в списке происходят последовательно, строго в показанном порядке.',exits=['forward'])
        else:
            out.update(location='ворота',query={'item':self.target,'candidates':self.people[:]},exits=[])
        return out

    def step(self,action):
        if self.done:raise RuntimeError('game is over')
        self.turn+=1;valid=False
        if self.offset<len(self.events) and action=={'type':'move','direction':'forward'}:
            self.offset=0 if self.offset==-1 else self.offset+GROUP_SIZE
            valid=True;self.message='Вы пришли на следующую стоянку.'
        elif (self.offset>=len(self.events) and isinstance(action,dict) and set(action)=={'type','person'}
              and action.get('type')=='deliver' and action.get('person') in self.people):
            valid=True;self.done=True
            self.terminal_reason='completed' if action['person']==self.answer else 'incorrect_answer'
            self.message='Ответ принят.'
        else:self.message='Недопустимое действие.'
        if not valid:self.invalid_actions+=1
        if not self.done and self.turn>=self.max_turns:self.done=True;self.terminal_reason='turn_limit'
        return self.observe()

    def result(self):
        return {'version':VERSION,'axis':'memory-compact','seed':self.seed,'config':dict(self.config),
                'terminal_reason':self.terminal_reason,'turns':self.turn,'invalid_actions':self.invalid_actions,
                'completed':self.terminal_reason=='completed'}


def create_game(axis,seed,level):
    if axis!='memory-compact' or level not in LEVELS:raise ValueError('unsupported scenario')
    return Game(seed)


def allowed_actions(axis,obs):
    if axis!='memory-compact':raise ValueError('unsupported scenario')
    return [{'type':'move','direction':'forward'}]+[{'type':'deliver','person':p} for p in obs.get('query',{}).get('candidates',[])]
