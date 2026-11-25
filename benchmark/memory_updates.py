"""Memory episode with fact updates and recency lures.

A separate prototype; it does not modify memory_navigation or the fixed
probes. Each encounter is shown once. Persons return and change their
requests; only the final request counts. Model calls and persistence are the
runner's responsibility.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from benchmark.fixed_probes import _Stream

VERSION = 'memory-updates-0.3.0'
MAX_NOTES = 500
LEVELS = ('easy', 'medium', 'hard', 'extreme')
PARAMS = {
    'easy': {'persons': 4, 'updates': 2, 'similar': False},
    'medium': {'persons': 8, 'updates': 5, 'similar': False},
    'hard': {'persons': 12, 'updates': 9, 'similar': True},
    'extreme': {'persons': 20, 'updates': 16, 'similar': True},
}
ITEMS_DISTINCT = ('янтарный ключ', 'серебряный кубок', 'медный компас', 'нефритовый амулет',
                  'хрустальная сфера', 'книга приливов', 'железная корона', 'лунный амулет')
ITEMS_SIMILAR = ('серебряный ключ', 'серебряный кубок', 'серебряный компас', 'серебряный амулет',
                 'медный ключ', 'медный кубок', 'медный компас', 'медный амулет')
MAX_CHOICES = 6
SYSTEM_PROMPT = ('Вы получаете наблюдение каждого хода, а не всю историю заново. '
                 'На стоянках путники называют свои просьбы; одна из них — главное поручение. '
                 'Путники возвращаются и меняют просьбу: учитывается только последняя версия. '
                 'Двигайтесь действием {"type":"move","direction":"forward"}; на воротах ответьте '
                 '{"type":"answer","item":"название предмета"}: какой предмет просит главный путник '
                 'после всех изменений. В любое действие можно добавить поле "notes" (строка до '
                 '500 символов): оно будет показано в следующих наблюдениях в поле notes. '
                 'Прошлые ходы могут быть недоступны — ведите заметки. Только один JSON-объект за ход.')


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


def final_request(records, person):
    """Oracle ground truth: apply every update in order."""
    value = None
    for rec in records:
        if rec['person'] == person:
            value = rec['item']
    return value


class MemoryUpdatesGame:
    """Track the changing request of the main person through updates.

    The target's past values deliberately reappear as answer choices, so
    recognizing a familiar item does not solve the episode.
    """
    def __init__(self, seed, level):
        _validate(seed, level)
        self.seed, self.level = str(seed), level
        params = PARAMS[level]
        self.config = {'vector': 'memory-updates', 'level': level, **params}
        rng = _Stream(self.seed, f'{VERSION}:{level}')
        pool = ITEMS_SIMILAR if params['similar'] else ITEMS_DISTINCT
        numbers = list(range(1, params['persons'] + 1))
        rng.shuffle(numbers)
        persons = [f'Путник {n:02d}' for n in numbers]
        self.target_person = persons[0]
        current = {p: pool[rng.below(len(pool))] for p in persons}
        self.records = [{'person': self.target_person, 'item': current[self.target_person],
                         'main': True, 'update': False}]
        introductions = [{'person': p, 'item': current[p], 'main': False, 'update': False}
                         for p in persons[1:]]
        rng.shuffle(introductions)
        self.records.extend(introductions)
        update_persons = [persons[rng.below(len(persons))] for _ in range(params['updates'])]
        if self.target_person not in update_persons:
            # The first-mentioned value must always be a lure, never the answer.
            update_persons[rng.below(len(update_persons))] = self.target_person
        if update_persons[-1] == self.target_person:
            # The most recent mention must not point at the target's item.
            # With many updates the swap partner may itself be the target.
            partners = [i for i, p in enumerate(update_persons[:-1]) if p != self.target_person]
            if partners:
                swap = partners[rng.below(len(partners))]
                update_persons[swap], update_persons[-1] = update_persons[-1], update_persons[swap]
            else:
                # Every update hit the target: retarget the last one elsewhere.
                others = [p for p in persons if p != self.target_person]
                update_persons[-1] = others[rng.below(len(others))]
        initial = dict(current)
        for person in update_persons:
            # A new value always differs from the person's current one; for the
            # target it also differs from the initial request, so the
            # first-mentioned value can never cycle back into the answer.
            excluded = {current[person]}
            if person == self.target_person:
                excluded.add(initial[person])
            options = [item for item in pool if item not in excluded]
            current[person] = options[rng.below(len(options))]
            self.records.append({'person': person, 'item': current[person],
                                 'main': False, 'update': True})
        self.target_updates = sum(r['person'] == self.target_person and r['update']
                                  for r in self.records)
        self.answer = current[self.target_person]
        history = []
        for rec in self.records:
            if rec['person'] == self.target_person and rec['item'] not in history:
                history.append(rec['item'])
        lures = [item for item in history if item != self.answer]
        choices = [self.answer] + lures
        fillers = [item for item in pool if item not in choices]
        rng.shuffle(fillers)
        choices += fillers[:max(0, min(MAX_CHOICES, len(pool)) - len(choices))]
        rng.shuffle(choices)
        self.choices = choices
        self.index, self.turn, self.invalid_actions = 0, 0, 0
        self.max_turns = len(self.records) + 4
        self.done, self.terminal_reason, self.message = False, None, ''
        self.notes = ''

    def observe(self):
        obs = {'scenario': 'memory-updates', 'turn': self.turn, 'max_turns': self.max_turns,
               'done': self.done, 'message': self.message, 'notes': self.notes}
        if self.index < len(self.records):
            rec = self.records[self.index]
            obs['location'] = 'Стоянка'
            obs['encounter'] = {'person': rec['person'], 'request': rec['item'],
                                'main': rec['main'], 'update': rec['update']}
            obs['exits'] = ['forward']
        else:
            obs.update(location='Ворота',
                       query={'person': self.target_person,
                              'question': 'Какой предмет этот путник просит после всех изменений просьбы?',
                              'choices': list(self.choices)},
                       exits=[])
        return obs

    def step(self, action):
        if self.done:
            raise RuntimeError('game is over')
        self.turn += 1
        # An optional "notes" string rides along any action and is echoed in
        # later observations; invalid notes invalidate the whole action.
        notes_ok = True
        if isinstance(action, dict) and 'notes' in action:
            notes_ok = isinstance(action['notes'], str) and len(action['notes']) <= MAX_NOTES
        move = (isinstance(action, dict) and set(action) <= {'type', 'direction', 'notes'}
                and action.get('type') == 'move' and action.get('direction') == 'forward')
        answer = (isinstance(action, dict) and set(action) <= {'type', 'item', 'notes'}
                  and action.get('type') == 'answer' and action.get('item') in self.choices)
        valid = False
        if notes_ok and self.index < len(self.records) and move:
            self.index += 1
            valid, self.message = True, 'Вы прошли к следующей стоянке.'
        elif notes_ok and self.index == len(self.records) and answer:
            valid = True
            self.done = True
            self.terminal_reason = 'completed' if action['item'] == self.answer else 'incorrect_answer'
            self.message = 'Ответ принят.'
        else:
            self.message = 'Недопустимое действие.'
        if valid and isinstance(action, dict) and 'notes' in action:
            self.notes = action['notes']
        if not valid:
            self.invalid_actions += 1
        if not self.done and self.turn >= self.max_turns:
            self.done, self.terminal_reason = True, 'turn_limit'
        return self.observe()

    def result(self):
        return {'engine_version': VERSION, 'seed': self.seed, 'config': dict(self.config),
                'turns': self.turn, 'terminal_reason': self.terminal_reason,
                'completed': self.terminal_reason == 'completed',
                'invalid_actions': self.invalid_actions,
                'target_updates': self.target_updates}


def create_game(seed, level):
    return MemoryUpdatesGame(seed, level)
