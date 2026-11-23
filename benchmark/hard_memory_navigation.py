"""Hard, separately configurable memory and navigation episodes (development).

No state or answer may be passed to a model except via observe().  Worlds are
fully deterministic and the two axes are isolated scenarios, not score claims.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import hashlib
from pathlib import Path
from benchmark.fixed_probes import _DIRECTIONS, _OPPOSITE, _VECTORS, _Stream

VERSION = 'hard-memory-navigation-0.1.0'
LEVELS = ('base', 'hard', 'extreme')
MEMORY_SETTINGS = {'base': (6, 12, 3), 'hard': (10, 36, 6), 'extreme': (14, 72, 10)}
NAV_SETTINGS = {'base': 5, 'hard': 7, 'extreme': 9}
ITEMS = ('амулет','свиток','компас','фонарь','кольцо','ключ','кубок','плащ',
         'чаша','щит','корона','камень','кинжал','карта')
SYSTEM_PROMPTS = {
    'memory': ('Вы сопровождаете караван. Сначала видны участники и их предметы; '
               'на каждой следующей стоянке указано, какие двое одновременно обменялись '
               'всеми своими предметами. У каждого ровно один предмет. До ворот идите '
               '{"type":"move","direction":"forward"}. Только у ворот назовут предмет: '
               'определите его текущего владельца действием {"type":"deliver","person":"ID"}. '
               'Можно ответить только один раз; нужна точная последовательность обменов. '
               'На ход выведите один JSON-объект без дополнительных полей.'),
    'navigation': ('Исследуйте неизвестный лабиринт: видны название текущей комнаты, её выходы, '
                   'название цели и убежища. Проходы неизменны, двусторонни, направления '
                   'постоянны. Найдите цель, выполните {"type":"search"} и вернитесь в '
                   'убежище. Перемещение {"type":"move","direction":"north|east|south|west"}. '
                   'Карта не показывается, каждый ход расходуется; на ход — один JSON без лишних полей.')}


def source_fingerprint():
    h = hashlib.sha256()
    for p in (Path(__file__), Path(__file__).with_name('fixed_probes.py')):
        h.update(p.name.encode()+b'\0'+p.read_bytes()+b'\0')
    return h.hexdigest()


def _validate(seed, level):
    if isinstance(seed, bool) or not isinstance(seed, (str, int)):
        raise ValueError('seed must be a string or integer')
    if level not in LEVELS: raise ValueError('unknown level')


def _rng(seed, domain): return _Stream(str(seed), f'{VERSION}:{domain}')


class MemoryGame:
    """Track ownership updates; the item to deliver is unknown until the end."""
    def __init__(self, seed, level):
        _validate(seed, level)
        n, count, minimum = MEMORY_SETTINGS[level]
        rng = _rng(seed, f'memory:{level}')
        people = [f'житель-{i:02d}' for i in range(1, n+1)]
        items = list(ITEMS); rng.shuffle(items); items = items[:n]
        rng.shuffle(people)
        initial = dict(zip(people, items))
        # Require the queried item to actually move repeatedly, not end at its
        # original owner, and not participate in the last exchange. Both model
        # and evaluator use the same predetermined sequence (no score-driven retry).
        for _ in range(5000):
            target = items[rng.below(n)]
            holdings = dict(initial); events = []; target_touches = 0
            initial_owner = next(p for p in people if initial[p] == target)
            for j in range(count):
                a = people[rng.below(n)]
                other = [p for p in people if p != a]; b = other[rng.below(len(other))]
                touches = target in (holdings[a], holdings[b])
                target_touches += int(touches)
                events.append({'people': [a,b]})
                holdings[a], holdings[b] = holdings[b], holdings[a]
                last_touches = touches
            final_owner = next(p for p in people if holdings[p] == target)
            if target_touches >= minimum and not last_touches and final_owner != initial_owner:
                break
        else:
            raise RuntimeError('could not construct memory episode')
        # Vary display order independently; correct answer is never a position.
        assignments = [{'person': p, 'item': initial[p]} for p in people]
        rng.shuffle(assignments)
        self.initial, self.events, self.target, self.answer = assignments, events, target, final_owner
        self.people = sorted(people)
        self.seed, self.level, self.index, self.turn = str(seed), level, 0, 0
        self.max_turns = 1 + count + 1 + 4
        self.invalid_actions = 0
        self.done = False; self.terminal_reason = None; self.message = 'Начало путешествия.'
        self.config = {'axis':'memory','level':level,'people':n,'exchanges':count}

    def observe(self):
        out = {'version':VERSION, 'axis':'memory', 'turn':self.turn, 'max_turns':self.max_turns,
               'done':self.done, 'message':self.message}
        if self.index == 0:
            out.update(location='лагерь', assignments=deepcopy(self.initial), exits=['forward'])
        elif self.index <= len(self.events):
            out.update(location='стоянка', event=deepcopy(self.events[self.index-1]), exits=['forward'])
        else:
            out.update(location='ворота', query={'item':self.target, 'candidates':self.people[:]}, exits=[])
        return out

    def step(self, action):
        if self.done: raise RuntimeError('game is over')
        self.turn += 1
        valid = False
        if self.index <= len(self.events) and action == {'type':'move','direction':'forward'}:
            self.index += 1; valid = True; self.message = 'Вы пришли на следующую стоянку.'
        elif (self.index > len(self.events) and isinstance(action,dict)
              and set(action) == {'type','person'} and action.get('type') == 'deliver'
              and action.get('person') in self.people):
            valid = True; self.done = True
            self.terminal_reason = 'completed' if action['person'] == self.answer else 'incorrect_answer'
            self.message = 'Ответ принят.'
        else: self.message = 'Недопустимое действие.'
        if not valid: self.invalid_actions += 1
        if not self.done and self.turn >= self.max_turns:
            self.done = True; self.terminal_reason = 'turn_limit'
        return self.observe()

    def result(self):
        return {'version':VERSION,'axis':'memory','seed':self.seed,'config':dict(self.config),
                'terminal_reason':self.terminal_reason,'turns':self.turn,
                'invalid_actions':self.invalid_actions,'completed':self.terminal_reason == 'completed'}


class NavigationGame:
    """Explore a cyclic maze, collect the object, and return to the start."""
    def __init__(self, seed, level):
        _validate(seed, level)
        side = NAV_SETTINGS[level]; rng = _rng(seed, f'navigation:{level}')
        cells = [(x,y) for y in range(side) for x in range(side)]
        self.edges = {cell:{} for cell in cells}
        start = cells[rng.below(len(cells))]
        seen, stack = {start}, [start]
        while stack:
            p = stack[-1]
            options = [(d, (p[0]+v[0],p[1]+v[1])) for d,v in _VECTORS.items()
                       if (p[0]+v[0],p[1]+v[1]) in self.edges and (p[0]+v[0],p[1]+v[1]) not in seen]
            if not options: stack.pop(); continue
            direction, dest = options[rng.below(len(options))]
            self.edges[p][direction] = dest; self.edges[dest][_OPPOSITE[direction]] = p
            seen.add(dest); stack.append(dest)
        extras = [(p,d,(p[0]+v[0],p[1]+v[1])) for p in cells for d,v in _VECTORS.items()
                  if d in ('east','south') and (p[0]+v[0],p[1]+v[1]) in self.edges and d not in self.edges[p]]
        rng.shuffle(extras)
        # Loops require route mapping rather than only remembering tree parents.
        for p,d,q in extras[:max(1,len(extras)//4)]:
            self.edges[p][d] = q; self.edges[q][_OPPOSITE[d]] = p
        distance = {start:0}; todo = deque([start])
        while todo:
            p = todo.popleft()
            for q in self.edges[p].values():
                if q not in distance: distance[q]=distance[p]+1; todo.append(q)
        farthest = max(distance.values())
        choices = [p for p in cells if p != start and distance[p] >= max(side, (farthest+1)//2)]
        if not choices: raise RuntimeError('cannot select distant goal')
        target = choices[rng.below(len(choices))]
        labels = [f'Зал-{i:03}' for i in range(1,len(cells)+1)]; rng.shuffle(labels)
        self.names = dict(zip(cells,labels)); self.home = self.position = start; self.target = target
        self.optimal_distance = distance[target]; self.seed = str(seed); self.level = level
        self.turn=0; self.max_turns=4*(len(cells)-1)+4; self.invalid_actions=0
        self.done=False; self.terminal_reason=None; self.has_relic=False
        self.visited={start}; self.message='Вы начинаете в убежище.'
        self.config={'axis':'navigation','level':level,'side':side,'rooms':len(cells)}

    def observe(self):
        return {'version':VERSION,'axis':'navigation','room':self.names[self.position],
                'home':self.names[self.home],'goal':self.names[self.target],
                'exits':[d for d in _DIRECTIONS if d in self.edges[self.position]],
                'relic':self.has_relic,'turn':self.turn,'max_turns':self.max_turns,
                'done':self.done,'message':self.message}

    def step(self,action):
        if self.done: raise RuntimeError('game is over')
        self.turn += 1; valid=False
        if isinstance(action,dict) and set(action)=={'type','direction'} and action.get('type')=='move':
            d=action.get('direction')
            if isinstance(d,str) and d in self.edges[self.position]:
                self.position=self.edges[self.position][d];self.visited.add(self.position)
                valid=True;self.message='Вы перешли в другую комнату.'
        elif action == {'type':'search'} and self.position==self.target and not self.has_relic:
            valid=True;self.has_relic=True;self.message='Реликвия найдена; вернитесь в убежище.'
        if not valid:
            self.invalid_actions+=1;self.message='Недопустимое действие.'
        if self.has_relic and self.position==self.home:
            self.done=True;self.terminal_reason='completed'
        elif self.turn>=self.max_turns:
            self.done=True;self.terminal_reason='turn_limit'
        return self.observe()

    def result(self):
        return {'version':VERSION,'axis':'navigation','seed':self.seed,'config':dict(self.config),
                'terminal_reason':self.terminal_reason,'turns':self.turn,'invalid_actions':self.invalid_actions,
                'completed':self.terminal_reason=='completed','rooms_visited':len(self.visited),
                'rooms_total':len(self.names),'shortest_one_way':self.optimal_distance,'relic':self.has_relic}


def create_game(axis,seed,level):
    if axis == 'memory': return MemoryGame(seed,level)
    if axis == 'navigation': return NavigationGame(seed,level)
    raise ValueError('unknown axis')


def allowed_actions(axis, obs):
    if axis == 'memory':
        result=[{'type':'move','direction':'forward'}]
        result += [{'type':'deliver','person':name} for name in obs.get('query',{}).get('candidates',[])]
        return result
    if axis == 'navigation':
        return [{'type':'move','direction':d} for d in _DIRECTIONS] + [{'type':'search'}]
    raise ValueError('unknown axis')

COMPACT_VERSION = 'hard-memory-navigation-compact-0.1.0'


class CompactMemoryGame:
    """Group up to six observed exchanges per model turn without hiding events.

    This is a distinct protocol, not equivalent to a turn-by-turn model run:
    the model sees each exchange but is not asked to choose between them.
    """
    def __init__(self,seed,level,*,group_size=6):
        if type(group_size) is not int or not 1 <= group_size <= 6:
            raise ValueError('group size must be an integer in 1..6')
        raw=MemoryGame(seed,level)
        self.initial,self.events,self.target,self.answer,self.people = (raw.initial,raw.events,raw.target,raw.answer,raw.people)
        self.seed,self.level,self.group_size=str(seed),level,group_size
        self.offset=-1;self.turn=0;self.invalid_actions=0
        self.max_turns=1+(len(self.events)+group_size-1)//group_size+1+4
        self.done=False;self.terminal_reason=None;self.message='Начало путешествия.'
        self.config={**raw.config,'protocol':'grouped-events-v1','group_size':group_size}

    def observe(self):
        out={'version':COMPACT_VERSION,'axis':'memory','turn':self.turn,'max_turns':self.max_turns,
             'done':self.done,'message':self.message}
        if self.offset==-1:
            out.update(location='лагерь',assignments=deepcopy(self.initial),exits=['forward'])
        elif self.offset < len(self.events):
            out.update(location='стоянка',events=deepcopy(self.events[self.offset:self.offset+self.group_size]),
                       rules='Обмены в списке происходят последовательно, строго в показанном порядке.',exits=['forward'])
        else:
            out.update(location='ворота',query={'item':self.target,'candidates':self.people[:]},exits=[])
        return out

    def step(self,action):
        if self.done:raise RuntimeError('game is over')
        self.turn+=1;valid=False
        if self.offset < len(self.events) and action=={'type':'move','direction':'forward'}:
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
        return {'version':COMPACT_VERSION,'axis':'memory','seed':self.seed,'config':dict(self.config),
                'terminal_reason':self.terminal_reason,'turns':self.turn,'invalid_actions':self.invalid_actions,
                'completed':self.terminal_reason=='completed'}


def create_compact_memory_game(seed,level,*,group_size=6):
    return CompactMemoryGame(seed,level,group_size=group_size)


COMPACT_MEMORY_PROMPT = (
    'Вы сопровождаете караван. Сначала видны участники и их предметы; затем каждая '
    'стоянка показывает последовательный список обменов. Выполняйте обмены строго '
    'по порядку: двое меняются своими единственными предметами. Продолжайте '
    '{"type":"move","direction":"forward"}. У ворот назовут предмет; выберите '
    'его текущего владельца {"type":"deliver","person":"ID"}. Ответить можно '
    'лишь один раз. Один JSON-объект на ход, без дополнительных полей.'
)
