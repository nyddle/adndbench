"""Opt-in adventure combining map exploration, one-shot clues and quest chains.

This is independent of expedition and does not implement party or combat.
The host runner controls context and is responsible for private persistence.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import hashlib
from pathlib import Path
from benchmark.fixed_probes import _DIRECTIONS, _OPPOSITE, _VECTORS, _Stream

VERSION = 'adventure-vectors-0.1.0'
LEVELS = ('easy', 'medium', 'hard')
RUNES = ('sun', 'moon', 'star', 'tree')
MEMORY_LENGTHS = {'easy': 1, 'medium': 2, 'hard': 3}
QUEST_LENGTHS = {'easy': 1, 'medium': 3, 'hard': 5}
SYSTEM_PROMPT = (
    'Верните реликвию в убежище. В начале поговорите с хранителем действием {"type":"talk"}; '
    'он только один раз назовёт последовательность рун для замка. Запомните порядок. '
    'Исследуйте комнаты действием {"type":"move","direction":"north|east|south|west"}; '
    'видны текущая комната и её выходы, проходы постоянны и обратимы. '
    'Для заданий доступны их ID, названия комнат и зависимости requires: '
    'в нужной комнате выполните {"type":"interact","target":"ID"}, когда выполнены все зависимости. '
    'После всех этапов найдите комнату с замком и откройте его действием '
    '{"type":"unlock","code":"sun-moon-..."}, перечислив руны в точном порядке через дефис. '
    'Есть только одна попытка; неверный код завершает партию. Затем вернитесь в убежище. '
    'Одно действие — один JSON-объект без дополнительных полей; неверное действие тратит ход.')


def source_fingerprint():
    h = hashlib.sha256()
    for p in (Path(__file__), Path(__file__).with_name('fixed_probes.py')):
        h.update(p.name.encode() + b'\0' + p.read_bytes() + b'\0')
    return h.hexdigest()


def _rng(seed, domain):
    return _Stream(str(seed), f'{VERSION}:{domain}')


def _build_world(seed, navigation):
    # The tree, shuffled extra edges, labels and sites are generated before
    # selecting an edge prefix. Thus levels form nested versions of one world.
    rng = _rng(seed, 'map')
    cells = [(x, y) for y in range(4) for x in range(4)]
    tree = {p: {} for p in cells}
    seen, stack = {(0, 0)}, [(0, 0)]
    while stack:
        p = stack[-1]
        options = [(d, (p[0]+v[0], p[1]+v[1])) for d,v in _VECTORS.items()
                   if (p[0]+v[0], p[1]+v[1]) in tree and (p[0]+v[0], p[1]+v[1]) not in seen]
        if not options:
            stack.pop(); continue
        d, q = options[rng.below(len(options))]
        tree[p][d] = q; tree[q][_OPPOSITE[d]] = p
        seen.add(q); stack.append(q)
    extra = [(p,d,(p[0]+v[0],p[1]+v[1])) for p in cells for d,v in _VECTORS.items()
             if d in ('east', 'south') and (p[0]+v[0],p[1]+v[1]) in tree and d not in tree[p]]
    rng.shuffle(extra)
    count = {'hard':0, 'medium':len(extra)//2, 'easy':len(extra)}[navigation]
    for p,d,q in extra[:count]: tree[p][d]=q; tree[q][_OPPOSITE[d]]=p
    labels = [f'Локация {i:02d}' for i in range(1,17)]; rng.shuffle(labels)
    names = dict(zip(cells, labels))
    sites = cells[1:]; rng.shuffle(sites)
    return tree, names, cells[0], sites[:5], sites[5]


class Game:
    def __init__(self, seed: str | int, *, memory: str = 'easy', navigation: str = 'easy',
                 quests: str = 'easy', max_turns: int = 200):
        if not isinstance(seed, (str, int)) or isinstance(seed, bool): raise ValueError('invalid seed')
        if any(x not in LEVELS for x in (memory, navigation, quests)): raise ValueError('invalid level')
        if type(max_turns) is not int or max_turns < 1: raise ValueError('invalid max_turns')
        self.seed = str(seed)
        self.config = {'memory':memory, 'navigation':navigation, 'quests':quests, 'max_turns':max_turns}
        self.edges, self.names, self.home, sites, self.lock = _build_world(self.seed, navigation)
        rng = _rng(seed, 'memory')
        # Prefixes preserve the earlier runes when the memory level changes.
        full_code = [RUNES[rng.below(len(RUNES))] for _ in range(3)]
        self.code = full_code[:MEMORY_LENGTHS[memory]]
        self.tasks = [{'id':f'Q{i+1}', 'room':self.names[sites[i]],
                       'description': ('Попросить подсказку', 'Найти ингредиент', 'Поговорить с магом',
                                       'Получить оберег', 'Отыскать ключ')[i],
                       'requires': [] if i == 0 else [f'Q{i}']}
                      for i in range(QUEST_LENGTHS[quests])]
        self.position, self.turn, self.max_turns = self.home, 0, max_turns
        self.briefed = False
        self.completed_tasks = set()
        self.unlocked = False
        self.visited = {self.home}
        self.invalid_actions = 0
        self.done, self.terminal_reason = False, None
        self.notice = {'text':'Вы в убежище. Поговорите с хранителем.'}

    def observe(self):
        # Only the current room exits and the current event are shown; the
        # private map, original code and previous events are never returned.
        return {'version': VERSION, 'room':self.names[self.position],
                'home':self.names[self.home],
                'exits':[d for d in _DIRECTIONS if d in self.edges[self.position]],
                'briefed':self.briefed,
                'tasks':deepcopy(self.tasks) if self.briefed else [],
                'completed_tasks': sorted(self.completed_tasks),
                'lock_room':self.names[self.lock] if self.briefed else None,
                'relic':self.unlocked, 'turn':self.turn, 'max_turns':self.max_turns,
                'notice':deepcopy(self.notice), 'done':self.done}

    def step(self, action):
        if self.done: raise RuntimeError('episode is over')
        self.turn += 1
        valid = False
        self.notice = {'text':'Действие не выполнено.'}
        if isinstance(action,dict) and action == {'type':'talk'} and self.position == self.home:
            valid = True
            if not self.briefed:
                self.briefed = True
                self.notice = {'text':'Хранитель сообщил код один раз.','runes':self.code[:]}
            else:
                self.notice = {'text':'Хранитель больше не повторяет код.'}
        elif isinstance(action,dict) and set(action) == {'type','direction'} and action.get('type') == 'move':
            direction = action.get('direction')
            if isinstance(direction,str) and direction in self.edges[self.position]:
                self.position = self.edges[self.position][direction]
                self.visited.add(self.position)
                valid = True
                self.notice = {'text':'Вы перешли в другую локацию.'}
        elif isinstance(action,dict) and set(action) == {'type','target'} and action.get('type') == 'interact' and self.briefed:
            target = action.get('target')
            task = next((t for t in self.tasks if t['id'] == target), None)
            if task and task['id'] not in self.completed_tasks and task['room'] == self.names[self.position] and set(task['requires']) <= self.completed_tasks:
                self.completed_tasks.add(task['id']); valid = True
                self.notice = {'text':f"Выполнен этап {task['id']}."}
        elif isinstance(action,dict) and set(action) == {'type','code'} and action.get('type') == 'unlock' and self.briefed and self.position == self.lock and len(self.completed_tasks) == len(self.tasks) and not self.unlocked:
            code = action.get('code')
            if isinstance(code,str):
                valid = True
                if code == '-'.join(self.code):
                    self.unlocked = True
                    self.notice = {'text':'Замок открыт; возьмите реликвию и вернитесь домой.'}
                else:
                    self.done, self.terminal_reason = True, 'incorrect_code'
                    self.notice = {'text':'Код неверный; попыток больше нет.'}
        if not valid: self.invalid_actions += 1
        if not self.done and self.unlocked and self.position == self.home:
            self.done, self.terminal_reason = True, 'completed'
        elif not self.done and self.turn >= self.max_turns:
            self.done, self.terminal_reason = True, 'turn_limit'
        return self.observe()

    def result(self):
        return {'version':VERSION, 'seed':self.seed, 'config':dict(self.config), 'turns':self.turn,
                'terminal_reason':self.terminal_reason, 'completed_tasks':len(self.completed_tasks),
                'tasks_total':len(self.tasks), 'visited_rooms':len(self.visited),
                'invalid_actions':self.invalid_actions, 'relic':self.unlocked}


def shortest_directions(edges, start, goal):
    """Privileged BFS; diagnostic oracle only, never pass the map to a model."""
    queue = deque([(start, [])]); seen = {start}
    while queue:
        p, path = queue.popleft()
        if p == goal: return path
        for direction, dest in edges[p].items():
            if dest not in seen:
                seen.add(dest); queue.append((dest,path+[direction]))
    raise ValueError('unreachable room')


def oracle(game):
    """Solve from the initial state with private map and clue; not an agent baseline."""
    if game.turn: raise ValueError('oracle expects initial state')
    actions = [{'type':'talk'}]
    position = game.home
    for task in game.tasks:
        target = next(p for p,name in game.names.items() if name == task['room'])
        path = shortest_directions(game.edges, position, target)
        actions.extend({'type':'move','direction':d} for d in path)
        actions.append({'type':'interact','target':task['id']})
        position = target
    path = shortest_directions(game.edges, position, game.lock)
    actions.extend({'type':'move','direction':d} for d in path)
    actions.append({'type':'unlock','code':'-'.join(game.code)})
    path = shortest_directions(game.edges, game.lock, game.home)
    actions.extend({'type':'move','direction':d} for d in path)
    return actions
