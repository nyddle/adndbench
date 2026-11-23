"""Long-form opt-in adventure with quest resources, discovery, party and combat.

Independent per-axis controls. This research prototype does not alter earlier
engines; quests are legible, while the map and the one-time code are not.
"""
from __future__ import annotations
from copy import deepcopy
from collections import deque
from pathlib import Path
import hashlib
from benchmark import adventure_vectors, quest_trial
from benchmark.fixed_probes import _DIRECTIONS, _Stream
from benchmark.party_combat import Party, Battle, RULES
from benchmark.party_adventure import ENCOUNTERS

VERSION='radical-adventure-0.1.0'
MEMORY_LENGTH={'easy':1,'medium':2,'hard':3,'extreme':4}
SYSTEM_PROMPT=(
    'В убежище поговорите с хранителем {"type":"talk"}: он один раз сообщит код. '
    'Исследуйте неизвестный мир действием {"type":"move","direction":"north|east|south|west"}. '
    'Завершите главное задание: его журнал показывает условия, эффекты и имена локаций. '
    'Действие выполняется только в указанной комнате: {"type":"perform","target":"ID"}. '
    'Действия одноразовые; consumes удаляет предметы, produces добавляет их; optional '
    'обмены могут потратить предметы, нужные главной цепочке. Неверное действие тратит ход. '
    'Перед финальным действием в его комнате откройте замок {"type":"unlock","code":"sun-moon-..."}. '
    'Длина кода и допустимые руны известны из подсказки, порядок надо запомнить. '
    'Неверный код завершает партию. Если включён бой, он начинается после верного кода; '
    'до победы уйти нельзя. Кандидатов в текущей комнате можно нанять '
    '{"type":"recruit","candidate":"ID"}. В бою используйте '
    '{"type":"strike|guard|heal|blast","actor":"ID","target":"ID"}, '
    'его правила и намерения врагов показываются в наблюдении. Победив, выполните финальное действие. '
    'Каждый ход — ровно один JSON-объект без лишних полей.')


def source_fingerprint():
    h=hashlib.sha256()
    for name in ('radical_adventure.py','quest_trial.py','adventure_vectors.py','fixed_probes.py','party_combat.py','party_adventure.py'):
        p=Path(__file__).with_name(name);h.update(name.encode()+b'\0'+p.read_bytes()+b'\0')
    return h.hexdigest()


def shortest_directions(edges,start,goal):
    q=deque([(start,())]);seen={start}
    while q:
        cell,path=q.popleft()
        if cell==goal:return list(path)
        for direction,nxt in edges[cell].items():
            if nxt not in seen:seen.add(nxt);q.append((nxt,path+(direction,)))
    raise ValueError('unreachable target')


class Game:
    def __init__(self,seed:str|int,*,memory='medium',navigation='medium',quests='hard',
                 combat='medium',party=True,max_allies=2,max_turns=300):
        if not isinstance(seed,(str,int)) or isinstance(seed,bool):raise ValueError('invalid seed')
        if memory not in MEMORY_LENGTH or navigation not in adventure_vectors.LEVELS or quests not in quest_trial.LEVELS:
            raise ValueError('invalid difficulty')
        if combat not in ('off',*ENCOUNTERS) or type(party) is not bool or type(max_turns) is not int or max_turns<1:
            raise ValueError('invalid settings')
        self.seed=str(seed);self.memory=memory;self.navigation=navigation;self.quests=quests
        self.combat=combat;self.party_enabled=party;self.max_turns=max_turns
        self.edges,self.names,self.home,_,_=adventure_vectors._build_world(self.seed,navigation)
        self.quest=quest_trial.QuestTrial(seed,quests,max_turns=10000)
        rng=_Stream(self.seed,f'{VERSION}:sites:{quests}')
        sites=list(self.names);sites.remove(self.home);rng.shuffle(sites)
        # Group tasks across eight named locations; the mapping is independent
        # of memory, navigation, party, combat and arbitrary action order.
        self.task_rooms={task['id']:sites[i%8] for i,task in enumerate(self.quest.plan['tasks'])}
        self.goal_room=self.task_rooms[self.quest.plan['goal']]
        code_rng=_Stream(self.seed,f'{VERSION}:code')
        self.code=[adventure_vectors.RUNES[code_rng.below(len(adventure_vectors.RUNES))] for _ in range(MEMORY_LENGTH[memory])]
        self.members=Party(max_allies=max_allies if party else 0)
        r=_Stream(self.seed,f'{VERSION}:candidates');candidate_sites=list(self.names);r.shuffle(candidate_sites)
        self.candidates={}
        if party:
            for i,role in enumerate(('warden','medic','mage')):self.candidates.setdefault(candidate_sites[i],[]).append(role)
        self.position=self.home;self.visited={self.home};self.turn=0;self.invalid_actions=0
        self.briefed=False;self.unlocked=False;self.done=False;self.terminal_reason=None
        self.battle=None;self.encounter_won=False
        self.notice={'text':'Вы в убежище. Поговорите с хранителем.'}

    def observe(self):
        tasks=[]
        if self.briefed:
            tasks=[{**deepcopy(t),'room':self.names[self.task_rooms[t['id']]]} for t in self.quest.plan['tasks']]
        obs={'version':VERSION,'room':self.names[self.position], 'home':self.names[self.home],
             'exits':[d for d in _DIRECTIONS if d in self.edges[self.position]],
             'goal':self.quest.plan['goal'] if self.briefed else None,'tasks':tasks,
             'completed':sorted(self.quest.completed),'inventory':sorted(self.quest.inventory),
             'briefed':self.briefed,'unlocked':self.unlocked,'turn':self.turn,
             'max_turns':self.max_turns,'done':self.done,'notice':deepcopy(self.notice),
             'party':self.members.observe(present=self.candidates.get(self.position,[])),
             'battle':self.battle.observe() if self.battle and self.battle.status=='ongoing' else None,
             'encounter':{'enabled':self.combat!='off','won':self.encounter_won}}
        if self.combat!='off':obs.update(combat_rules=RULES,scouting=deepcopy(ENCOUNTERS[self.combat]))
        return obs

    def _goal_ready(self):
        task=next(t for t in self.quest.plan['tasks'] if t['id']==self.quest.plan['goal'])
        return quest_trial._legal(task,frozenset(self.quest.completed),frozenset(self.quest.inventory))

    def _irrecoverable_quest_state(self):
        # The quest ledger completely defines all items and one-shot producers.
        # Walk backwards from goal, then detect a required item whose sole
        # producer has already fired and whose required consumer is unfinished.
        tasks={t['id']:t for t in self.quest.plan['tasks']}
        relevant=set();stack=[self.quest.plan['goal']]
        while stack:
            task_id=stack.pop()
            if task_id in relevant: continue
            relevant.add(task_id);stack.extend(tasks[task_id]['requires'])
        producers={item:t['id'] for t in tasks.values() for item in t['produces']}
        for task_id in relevant - self.quest.completed:
            for item in tasks[task_id]['consumes']:
                if item not in self.quest.inventory and producers.get(item) in self.quest.completed:
                    return True
        return False

    def step(self,action):
        if self.done:raise RuntimeError('game is over')
        self.turn+=1;valid=False;self.notice={'text':'Действие не выполнено.'}
        if self.battle and self.battle.status=='ongoing':
            self.battle.step(action);valid=self.battle.events[-1]['valid']
            self.notice={'text':'Действие в бою выполнено.' if valid else 'Недопустимое действие; враги ответили.'}
            if self.battle.status=='victory':self.encounter_won=True;self.notice={'text':'Противники побеждены.'}
            elif self.battle.status in ('defeat','timeout'):
                self.done=True;self.terminal_reason='death' if self.battle.status=='defeat' else 'combat_limit'
        elif action=={'type':'talk'} and self.position==self.home:
            valid=True
            if not self.briefed:
                self.briefed=True;self.notice={'text':'Хранитель сообщил код только один раз.','runes':self.code[:]}
            else:self.notice={'text':'Хранитель не повторяет код.'}
        elif isinstance(action,dict) and set(action)=={'type','direction'} and action.get('type')=='move':
            d=action.get('direction')
            if isinstance(d,str) and d in self.edges[self.position]:
                self.position=self.edges[self.position][d];self.visited.add(self.position);valid=True
                self.notice={'text':'Вы перешли в другую локацию.'}
            else:self.notice={'text':'В этом направлении выхода нет.'}
        elif isinstance(action,dict) and set(action)=={'type','candidate'} and action.get('type')=='recruit':
            valid=bool(self.party_enabled and self.members.recruit(action.get('candidate'),present=self.candidates.get(self.position,[])))
            self.notice={'text':'Союзник присоединился.' if valid else 'Нельзя нанять персонажа здесь.'}
        elif isinstance(action,dict) and set(action)=={'type','code'} and action.get('type')=='unlock' and self.briefed and self.position==self.goal_room and self._goal_ready() and not self.unlocked:
            if isinstance(action.get('code'),str):
                valid=True
                if action['code']!='-'.join(self.code):
                    self.done=True;self.terminal_reason='incorrect_code';self.notice={'text':'Код неверный; попыток больше нет.'}
                else:
                    self.unlocked=True;self.notice={'text':'Код верный.'}
                    if self.combat!='off':
                        self.battle=Battle(self.members,deepcopy(ENCOUNTERS[self.combat]));self.notice={'text':'Код верный; начался бой.'}
        elif isinstance(action,dict) and set(action)=={'type','target'} and action.get('type')=='perform' and self.briefed:
            target=action.get('target')
            if (isinstance(target,str) and target in self.task_rooms and self.position==self.task_rooms[target]
                and (target!=self.quest.plan['goal'] or (self.unlocked and (self.combat=='off' or self.encounter_won)))):
                before=self.quest.invalid_actions;self.quest.step(action);valid=self.quest.invalid_actions==before
                self.notice={'text':self.quest.last_event}
                if self.quest.terminal_reason=='completed':self.done=True;self.terminal_reason='completed'
                elif valid and self._irrecoverable_quest_state():
                    self.done=True;self.terminal_reason='dead_end'
                    self.notice={'text':'Основной квест невыполним: необходимый предмет безвозвратно утрачен.'}
        if not valid:self.invalid_actions+=1
        if not self.done and self.turn>=self.max_turns:self.done=True;self.terminal_reason='turn_limit'
        return self.observe()

    def result(self):
        return {'version':VERSION,'config':{'memory':self.memory,'navigation':self.navigation,'quests':self.quests,
                                            'combat':self.combat,'party':self.party_enabled,'max_turns':self.max_turns},
                'turns':self.turn,'terminal_reason':self.terminal_reason,'invalid_actions':self.invalid_actions,
                'rooms_visited':len(self.visited),'rooms_total':len(self.names),'completed_tasks':len(self.quest.completed),
                'recruited':self.members.recruited[:],'combat_status':self.battle.status if self.battle else None,
                'combat_rounds':self.battle.round if self.battle else 0,'unlocked':self.unlocked}
