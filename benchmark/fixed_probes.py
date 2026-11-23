"""Seeded, common-state tasks with private answer keys.

Every model evaluated with the same (version, seed, difficulty) receives exactly
these public tasks, independent of its adventure trajectory. ``context`` is the
information given to the model; the answer can of course be inferred from it.
The private ``answer`` and seed must never be sent to the model. In particular,
the quest tasks present their entire history at question time: they measure
retrieval and use of context, not unaided long-term memory. Route tasks cover
only small, explicit navigation and do not establish general spatial ability.

This module does not define or expose a held-out seed set. Callers own seed
selection, storage, access control, and separation between development and test.
"""
from __future__ import annotations

import copy
import hashlib
import json
import unicodedata
from collections import deque
from typing import Any, Mapping

VERSION = 'fixed-probes-0.1.0'
DIFFICULTIES = ('easy', 'medium', 'hard')
_DIRECTIONS = ('north', 'east', 'south', 'west')
_VECTORS = {'north': (0, -1), 'east': (1, 0), 'south': (0, 1), 'west': (-1, 0)}
_OPPOSITE = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east'}
_ROOM_NAMES = ('Янтарный зал', 'Медная галерея', 'Лунная кузница', 'Башня туманов',
               'Сад колоколов', 'Красный двор', 'Каменный архив', 'Зал фонарей',
               'Старый колодец', 'Хрустальная лестница', 'Мшистый мост', 'Тихая башня',
               'Серебряная ротонда', 'Забытый склеп', 'Зеркальный зал', 'Звёздный двор')
_PEOPLE = ('Альма', 'Берен', 'Веста', 'Горн', 'Дара', 'Елисей', 'Жара', 'Зорин')
_ITEMS = ('серебряный ключ', 'янтарная печать', 'хрустальная сфера', 'медный компас',
          'книга приливов', 'лунный амулет', 'железная корона', 'нефритовый кубок')
_PLACES = ('Северная библиотека', 'Старая мельница', 'Горный пост', 'Речная пристань',
           'Тихая обсерватория', 'Каменная кузница', 'Лесная сторожка', 'Забытая часовня',
           'Сад фонарей', 'Медный храм', 'Зеркальное озеро', 'Башня корней')


class _Stream:
    """Stable per-task SHA-256 stream; no dependence on process hash order."""
    def __init__(self, seed: str, domain: str):
        self.seed, self.domain, self.counter = seed, domain, 0

    def below(self, n: int) -> int:
        if n < 1:
            raise ValueError('empty random range')
        limit = (1 << 256) - (1 << 256) % n
        while True:
            payload = json.dumps([VERSION, self.seed, self.domain, self.counter],
                                 ensure_ascii=False, separators=(',', ':'))
            self.counter += 1
            value = int.from_bytes(hashlib.sha256(payload.encode('utf-8')).digest(), 'big')
            if value < limit:
                return value % n

    def shuffle(self, values: list[Any]) -> None:
        for i in range(len(values) - 1, 0, -1):
            j = self.below(i + 1)
            values[i], values[j] = values[j], values[i]


def _probe(probe_id: str, capability: str, difficulty: str, context: dict[str, Any],
           question: str, answer: str) -> dict[str, Any]:
    return {'id': probe_id, 'capability': capability, 'difficulty': difficulty,
            'context': context, 'question': question, 'answer': answer}


def _displacement(seed: str, difficulty: str) -> dict[str, Any]:
    rng = _Stream(seed, f'{difficulty}:displacement')
    # Net displacement is non-zero and on exactly one axis. Mixed cancelling
    # pairs require adding several movements rather than copying the last one.
    answer = _DIRECTIONS[rng.below(len(_DIRECTIONS))]
    perpendicular = 'east' if answer in ('north', 'south') else 'north'
    net_steps, cancelling_pairs = {'easy': (1, 1), 'medium': (2, 2), 'hard': (3, 3)}[difficulty]
    steps = [answer] * net_steps
    for _ in range(cancelling_pairs):
        steps.extend((perpendicular, _OPPOSITE[perpendicular]))
    rng.shuffle(steps)
    # Copying the last direction alone must never solve the task.
    if steps[-1] == answer:
        index = next(i for i, direction in enumerate(steps) if direction != answer)
        steps[index], steps[-1] = steps[-1], steps[index]
    return _probe('spatial_displacement', 'spatial_reasoning', difficulty,
                  {'movements': steps, 'directions': list(_DIRECTIONS),
                   'rules': 'Направления постоянны; каждое перемещение равно одной клетке.'},
                  'В каком направлении от начальной точки находится конечная? '
                  'Ответьте одним из north, east, south, west.', answer)


def _route(seed: str, difficulty: str) -> dict[str, Any]:
    rng = _Stream(seed, f'{difficulty}:route')
    count = {'easy': 6, 'medium': 10, 'hard': 14}[difficulty]
    # Grow a randomized grid tree. A tree yields one unique path between every
    # pair: unlike a maze with ties, the requested first exit is unambiguous.
    positions = [(3, 3)]
    edges: dict[tuple[int, int], dict[str, tuple[int, int]]] = {positions[0]: {}}
    stack = [positions[0]]
    while len(positions) < count:
        if not stack:
            raise RuntimeError('could not generate route tree')
        x, y = stack[-1]
        candidates = [(direction, (x + dx, y + dy)) for direction, (dx, dy) in _VECTORS.items()
                      if 0 <= x + dx < 7 and 0 <= y + dy < 7 and (x + dx, y + dy) not in edges]
        if not candidates:
            stack.pop()
            continue
        direction, destination = candidates[rng.below(len(candidates))]
        edges[(x, y)][direction] = destination
        edges[destination] = {_OPPOSITE[direction]: (x, y)}
        positions.append(destination)
        stack.append(destination)
    labels = list(_ROOM_NAMES)
    rng.shuffle(labels)
    names = {position: labels[i] for i, position in enumerate(positions)}
    # Choose an interior room with at least two exits, not the DFS root: a
    # one-exit start would let the model answer without solving the route.
    candidates = []
    for candidate_start in positions:
        if len(edges[candidate_start]) < 2:
            continue
        queue = deque([(candidate_start, [])])
        visited = {candidate_start}
        while queue:
            position, current_path = queue.popleft()
            if len(current_path) >= 2:
                candidates.append((candidate_start, position, current_path))
            for direction in _DIRECTIONS:
                target = edges[position].get(direction)
                if target is not None and target not in visited:
                    visited.add(target)
                    queue.append((target, current_path + [direction]))
    if not candidates:
        raise RuntimeError('no non-trivial route with a choice of exits')
    maximum = max(len(path) for _, _, path in candidates)
    best = [candidate for candidate in candidates if len(candidate[2]) == maximum]
    start, farthest, path = best[rng.below(len(best))]
    rooms = [{'room': names[p], 'exits': {d: names[edges[p][d]] for d in _DIRECTIONS if d in edges[p]}}
             for p in positions]
    rng.shuffle(rooms)  # no positional inference from list order
    return _probe('spatial_route', 'spatial_reasoning', difficulty,
                  {'observed_map': rooms, 'rules': ('Указаны все проходы между комнатами; других проходов нет. '
                                                    'Каждый проход обратим и доступен.')},
                  f'Вы находитесь в «{names[start]}». Какой первый выход ведёт кратчайшим путём '
                  f'в «{names[farthest]}»? Ответьте одним из north, east, south, west.', path[0])


def _quest_probes(seed: str, difficulty: str) -> list[dict[str, Any]]:
    rng = _Stream(seed, f'{difficulty}:quests')
    count = {'easy': 3, 'medium': 5, 'hard': 8}[difficulty]
    people, items, places = list(_PEOPLE), list(_ITEMS), list(_PLACES)
    for values in (people, items, places):
        rng.shuffle(values)
    selected = rng.below(count)
    revised = (selected + 1 + rng.below(count - 1)) % count
    events = [f'{people[i]} просит найти {items[i]} в месте «{places[i]}».' for i in range(count)]
    # A later update supersedes the older source. The updated location has not
    # been used elsewhere, so no duplicate assignment creates ambiguity.
    new_location = places[count]
    events.append(f'Изменение поручения: {people[revised]} сообщает, что {items[revised]} '
                  f'теперь находится в месте «{new_location}», а не в прежнем месте.')
    context = {'history': events,
               'rules': 'Показана вся история; более позднее изменение заменяет прежние сведения.'}
    first = _probe('quest_assignment', 'quest_memory', difficulty, copy.deepcopy(context),
                   f'Какой предмет попросил найти {people[selected]}? Ответьте только названием предмета.',
                   items[selected])
    second = _probe('quest_update', 'quest_memory', difficulty, copy.deepcopy(context),
                    f'Где сейчас нужно найти {items[revised]} для персонажа {people[revised]}? '
                    'Ответьте только названием места.', new_location)
    return [first, second]


def _rotated_variants(probe: Mapping[str, Any], seed: str, difficulty: str) -> list[dict[str, Any]]:
    """Create four independently answerable orientations, one per direction.

    The seed shuffles their order so the public ordinal never identifies the
    answer. These are correlated rotations of one template, not independent
    observations for estimating uncertainty.
    """
    variants = []
    for rotation in range(4):
        variant = copy.deepcopy(dict(probe))
        rotate = lambda direction: _DIRECTIONS[(_DIRECTIONS.index(direction) + rotation) % 4]
        variant['answer'] = rotate(probe['answer'])
        if 'movements' in variant['context']:
            variant['context']['movements'] = [rotate(d) for d in variant['context']['movements']]
        else:
            for room in variant['context']['observed_map']:
                room['exits'] = {rotate(direction): name for direction, name in room['exits'].items()}
        variants.append(variant)
    _Stream(seed, f"{difficulty}:{probe['id']}:orientation-order").shuffle(variants)
    for index, variant in enumerate(variants, 1):
        variant['id'] = f"{probe['id']}_{index}"
    return variants


def generate_suite(seed: str | int, difficulty: str = 'medium') -> list[dict[str, Any]]:
    """Generate ten private, same-state probes for one seed and difficulty.

    Returns four rotated variants each of two spatial tasks, plus two
    quest-context tasks. Directions are balanced within a seed; the rotations
    are correlated and should be analyzed by seed. Each question must be sent
    independently, without another question's answer in model context. The list
    contains evaluator-only ``answer`` fields: pass each through ``public_probe``
    before sending it to a model. Difficulty controls movements, map nodes and
    distractors; comparisons across difficulty are different tasks, not a
    calibrated ability scale.
    """
    if not isinstance(seed, (str, int)) or isinstance(seed, bool):
        raise ValueError('seed must be a string or integer')
    if difficulty not in DIFFICULTIES:
        raise ValueError('difficulty must be easy, medium or hard')
    value = str(seed)
    return [*_rotated_variants(_displacement(value, difficulty), value, difficulty),
            *_rotated_variants(_route(value, difficulty), value, difficulty),
            *_quest_probes(value, difficulty)]


def public_probe(probe: Mapping[str, Any]) -> dict[str, Any]:
    """Copy only model-facing fields, with JSON response protocol and no seed/key."""
    return {'id': probe['id'], 'capability': probe['capability'],
            'difficulty': probe['difficulty'], 'context': copy.deepcopy(probe['context']),
            'question': probe['question'],
            'response_format': 'Верните только JSON-объект с полями id и answer (строки).' }


def _normalize(text: str) -> str:
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().strip().split())


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError('duplicate JSON key')
        output[key] = value
    return output


def check_response(probe: Mapping[str, Any], response: Any) -> bool:
    """Verify exactly {id, answer}; malformed/non-JSON outputs count as wrong.

    Case, Unicode normalization and incidental whitespace are normalized; no
    substring, fuzzy matching, implicit translation, or LLM judge is used.
    """
    if isinstance(response, str):
        try:
            response = json.loads(response, object_pairs_hook=_strict_object)
        except (ValueError, TypeError, RecursionError):
            return False
    if not isinstance(response, Mapping) or set(response) != {'id', 'answer'}:
        return False
    answer = response.get('answer')
    return (response.get('id') == probe.get('id') and isinstance(answer, str)
            and isinstance(probe.get('answer'), str)
            and _normalize(answer) == _normalize(probe['answer']))
