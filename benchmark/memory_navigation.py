"""Partially observed, replayable calibration micro-episodes.

This separate prototype does not modify expedition or earlier fixed probes.
Model calls and private persistence are the runner's responsibility.
"""
from __future__ import annotations

from collections import deque
import hashlib
from pathlib import Path
from benchmark.fixed_probes import _DIRECTIONS, _OPPOSITE, _Stream, _VECTORS

VERSION = 'memory-navigation-episodes-0.1.0'
LEVELS = ('easy', 'medium', 'hard')
MEMORY_DISTRACTORS = {'easy': 4, 'medium': 12, 'hard': 32}
NAV_SIDES = {'easy': 3, 'medium': 5, 'hard': 7}
ITEMS = ('янтарный ключ', 'серебряный кубок', 'медный компас', 'нефритовый амулет')
SYSTEM_PROMPTS = {
    'memory': ('Вы получаете наблюдение каждого хода, а не всю историю заново. '
               'На первой стоянке названо главное поручение. На остальных встречаются другие поручения. '
               'Двигайтесь действием {"type":"move","direction":"forward"}; на воротах '
               'ответьте {"type":"answer","item":"название предмета"}. Выберите предмет главного поручения. '
               'Только один JSON-объект за ход.'),
    'navigation': ('Исследуйте неизвестный лабиринт. Каждая комната имеет уникальное название; '
                   'в наблюдении видны только текущая комната, доступные направления и название цели. '
                   'Проходы двусторонние, их расположение постоянно. Постройте карту по наблюдениям; '
                   'достигните целевой комнаты до лимита ходов. Ход: '
                   '{"type":"move","direction":"north|east|south|west"}. '
                   'Только один JSON-объект за ход.')}


def source_fingerprint():
    digest = hashlib.sha256()
    for path in (Path(__file__), Path(__file__).with_name('fixed_probes.py')):
        digest.update(path.name.encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def _validate(seed, level):
    if not isinstance(seed, (str, int)) or isinstance(seed, bool):
        raise ValueError('seed must be a string or integer')
    if level not in LEVELS:
        raise ValueError('unknown difficulty')


def _rng(seed, domain):
    return _Stream(str(seed), f'{VERSION}:{domain}')


class MemoryGame:
    """Remember a single observed request through unrelated encounters.

    The target and past events are deliberately absent from later observations.
    The runner must specify what prior observations an agent can access.
    """
    def __init__(self, seed, level):
        _validate(seed, level)
        self.seed, self.level = str(seed), level
        self.config = {'vector': 'memory', 'level': level, 'distractors': MEMORY_DISTRACTORS[level]}
        rng = _rng(seed, f'memory:{level}')
        people = list(range(1, MEMORY_DISTRACTORS[level] + 2))
        rng.shuffle(people)
        self.target_person = f'Путник {people[0]:02d}'
        self.answer = ITEMS[rng.below(len(ITEMS))]
        self.records = [{'person': self.target_person, 'item': self.answer, 'main': True}]
        for number in people[1:]:
            self.records.append({'person': f'Путник {number:02d}', 'item': ITEMS[rng.below(len(ITEMS))], 'main': False})
        self.index, self.turn, self.invalid_actions = 0, 0, 0
        self.max_turns = len(self.records) + 4
        self.done, self.terminal_reason, self.message = False, None, ''

    def observe(self):
        obs = {'scenario': 'memory', 'turn': self.turn, 'max_turns': self.max_turns,
               'done': self.done, 'message': self.message}
        if self.index < len(self.records):
            rec = self.records[self.index]
            obs['location'] = 'Стоянка'
            obs['encounter'] = {'person': rec['person'], 'request': rec['item'], 'main': rec['main']}
            obs['exits'] = ['forward']
        else:
            obs.update(location='Ворота', query={'person': self.target_person,
                'question': 'Какой предмет просил этот путник в главном поручении?', 'choices': list(ITEMS)}, exits=[])
        return obs

    def step(self, action):
        if self.done:
            raise RuntimeError('game is over')
        self.turn += 1
        valid = False
        if self.index < len(self.records) and action == {'type': 'move', 'direction': 'forward'}:
            self.index += 1
            valid, self.message = True, 'Вы прошли к следующей стоянке.'
        elif self.index == len(self.records) and isinstance(action, dict) and set(action) == {'type', 'item'} and action['type'] == 'answer' and action['item'] in ITEMS:
            valid = True
            self.done = True
            self.terminal_reason = 'completed' if action['item'] == self.answer else 'incorrect_answer'
            self.message = 'Ответ принят.'
        else:
            self.message = 'Недопустимое действие.'
        if not valid:
            self.invalid_actions += 1
        if not self.done and self.turn >= self.max_turns:
            self.done, self.terminal_reason = True, 'turn_limit'
        return self.observe()

    def result(self):
        return {'engine_version': VERSION, 'seed': self.seed, 'config': dict(self.config),
                'turns': self.turn, 'terminal_reason': self.terminal_reason,
                'completed': self.terminal_reason == 'completed', 'invalid_actions': self.invalid_actions}


class NavigationGame:
    """Explore an unknown perfect grid maze; only current exits are visible."""
    def __init__(self, seed, level):
        _validate(seed, level)
        self.seed, self.level = str(seed), level
        side = NAV_SIDES[level]
        self.config = {'vector': 'navigation', 'level': level, 'side': side}
        rng = _rng(seed, f'navigation:{level}')
        cells = [(x, y) for y in range(side) for x in range(side)]
        self.edges = {p: {} for p in cells}
        root = cells[rng.below(len(cells))]
        visited, stack = {root}, [root]
        while stack:
            p = stack[-1]
            candidates = [(direction, (p[0]+delta[0], p[1]+delta[1]))
                          for direction, delta in _VECTORS.items()
                          if (p[0]+delta[0], p[1]+delta[1]) in self.edges
                          and (p[0]+delta[0], p[1]+delta[1]) not in visited]
            if not candidates:
                stack.pop(); continue
            direction, nxt = candidates[rng.below(len(candidates))]
            self.edges[p][direction] = nxt
            self.edges[nxt][_OPPOSITE[direction]] = p
            visited.add(nxt); stack.append(nxt)
        self.position = cells[rng.below(len(cells))]
        distance = {self.position: 0}
        todo = deque([self.position])
        while todo:
            p = todo.popleft()
            for nxt in self.edges[p].values():
                if nxt not in distance:
                    distance[nxt] = distance[p] + 1
                    todo.append(nxt)
        choices = [p for p in cells if distance[p] >= side]
        if not choices:
            raise RuntimeError('maze has no distant destination')
        self.target = choices[rng.below(len(choices))]
        self.optimal_path_length = distance[self.target]
        labels = [f'Комната {i:02d}' for i in range(1, len(cells)+1)]
        rng.shuffle(labels)
        self.names = dict(zip(cells, labels))
        self.turn, self.invalid_actions = 0, 0
        self.max_turns = 2 * (len(cells) - 1)
        self.visited = {self.position}
        self.done, self.terminal_reason, self.message = False, None, ''

    def observe(self):
        return {'scenario': 'navigation', 'room': self.names[self.position],
                'exits': [d for d in _DIRECTIONS if d in self.edges[self.position]],
                'goal': self.names[self.target], 'turn': self.turn, 'max_turns': self.max_turns,
                'done': self.done, 'message': self.message}

    def step(self, action):
        if self.done:
            raise RuntimeError('game is over')
        self.turn += 1
        if isinstance(action, dict) and set(action) == {'type', 'direction'} and action.get('type') == 'move' and isinstance(action.get('direction'), str) and action.get('direction') in self.edges[self.position]:
            self.position = self.edges[self.position][action['direction']]
            self.visited.add(self.position)
            self.message = 'Вы перешли в другую комнату.'
        else:
            self.invalid_actions += 1
            self.message = 'Недопустимое действие.'
        if self.position == self.target:
            self.done, self.terminal_reason = True, 'completed'
        elif self.turn >= self.max_turns:
            self.done, self.terminal_reason = True, 'turn_limit'
        return self.observe()

    def result(self):
        return {'engine_version': VERSION, 'seed': self.seed, 'config': dict(self.config),
                'turns': self.turn, 'terminal_reason': self.terminal_reason,
                'completed': self.terminal_reason == 'completed', 'invalid_actions': self.invalid_actions,
                'rooms_visited': len(self.visited), 'rooms_total': len(self.names),
                'optimal_path_length': self.optimal_path_length}


def create_game(vector, seed, level):
    if vector == 'memory':
        return MemoryGame(seed, level)
    if vector == 'navigation':
        return NavigationGame(seed, level)
    raise ValueError('unknown vector')
