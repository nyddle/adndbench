"""Unconditioned, paired short memory stories with nested prefixes.

Development-only; levels are hypotheses, not guaranteed model accuracies.
Observations reveal the full sequence in two groups and query an item only at
completion. Different worlds/seeds must remain private during model evaluation.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
from pathlib import Path
from benchmark.fixed_probes import _Stream
from benchmark.hard_memory_navigation import ITEMS, COMPACT_MEMORY_PROMPT

VERSION='balanced-short-memory-0.1.0'
LEVELS=('s4','s6','s8')
LENGTHS={'s4':4,'s6':6,'s8':8}
SYSTEM_PROMPT=COMPACT_MEMORY_PROMPT
PEOPLE_COUNT=6


def source_fingerprint():
    h=hashlib.sha256()
    for p in (Path(__file__),Path(__file__).with_name('hard_memory_navigation.py'),
              Path(__file__).with_name('fixed_probes.py')):
        h.update(p.name.encode()+b'\0'+p.read_bytes()+b'\0')
    return h.hexdigest()


def generate(seed):
    """One eight-event story; each prefix satisfies the same selection rules."""
    if isinstance(seed,bool) or not isinstance(seed,(str,int)):
        raise ValueError('seed must be a string or integer')
    rng=_Stream(str(seed),VERSION)
    people=[f'житель-{i:02d}' for i in range(1,PEOPLE_COUNT+1)]
    items=list(ITEMS);rng.shuffle(items);items=items[:PEOPLE_COUNT];rng.shuffle(people)
    initial=dict(zip(people,items))
    # Target and exchanges are sampled without conditioning on the answer,
    # last exchange, number of target transfers, or final owner. Consequently
    # simple biases reflect the process itself rather than a rejection rule.
    target=items[rng.below(PEOPLE_COUNT)]
    holdings=dict(initial);events=[];answers={}
    for n in range(1,9):
        a=people[rng.below(PEOPLE_COUNT)]
        candidates=[p for p in people if p!=a];b=candidates[rng.below(len(candidates))]
        events.append({'people':[a,b]});holdings[a],holdings[b]=holdings[b],holdings[a]
        if n in (4,6,8):answers[n]=next(p for p in people if holdings[p]==target)
    assignments=[{'person':p,'item':initial[p]} for p in people];rng.shuffle(assignments)
    return {'assignments':assignments,'events':events,'target':target,'answers':answers,'people':sorted(people)}


class Game:
    def __init__(self,seed:str|int,level:str):
        if level not in LEVELS:raise ValueError('unknown level')
        story=generate(seed);self.seed=str(seed);self.level=level;count=LENGTHS[level]
        self.initial=story['assignments'];self.events=story['events'][:count]
        self.target=story['target'];self.answer=story['answers'][count];self.people=story['people']
        self.group_size=count//2;self.offset=-1;self.turn=0;self.max_turns=8
        self.invalid_actions=0;self.done=False;self.terminal_reason=None;self.message='Начало путешествия.'
        self.config={'axis':'memory-compact','level':level,'people':PEOPLE_COUNT,'exchanges':count,
                     'groups':2,'group_size':self.group_size,'selection':'unconditioned'}

    def observe(self):
        out={'version':VERSION,'axis':'memory-compact','turn':self.turn,'max_turns':self.max_turns,
             'done':self.done,'message':self.message}
        if self.offset==-1:
            out.update(location='лагерь',assignments=deepcopy(self.initial),exits=['forward'])
        elif self.offset<len(self.events):
            out.update(location='стоянка',events=deepcopy(self.events[self.offset:self.offset+self.group_size]),
                       rules='Обмены в списке происходят последовательно, строго в показанном порядке.',exits=['forward'])
        else:
            out.update(location='ворота',query={'item':self.target,'candidates':self.people[:]},exits=[])
        return out

    def step(self,action):
        if self.done:raise RuntimeError('game is over')
        self.turn+=1;valid=False
        if self.offset<len(self.events) and action=={'type':'move','direction':'forward'}:
            self.offset=0 if self.offset==-1 else self.offset+self.group_size
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
    if axis!='memory-compact':raise ValueError('unknown axis')
    return Game(seed,level)


def allowed_actions(axis,obs):
    if axis!='memory-compact':raise ValueError('unknown axis')
    return [{'type':'move','direction':'forward'}]+[{'type':'deliver','person':p} for p in obs.get('query',{}).get('candidates',[])]
