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


# The v2 protocol is deliberately separate: generate_suite() and VERSION retain
# their original semantics for recorded evaluations.  A runner must explicitly
# opt in to generate_suite_v2 and record FIXED_PROBES_V2 in its experiment spec.
FIXED_PROBES_V2 = 'fixed-probes-0.2.0'


def _v2_rng(seed: str, domain: str) -> _Stream:
    return _Stream(seed, f'{FIXED_PROBES_V2}:{domain}')


def _v2_displacement(seed: str, difficulty: str) -> list[dict[str, Any]]:
    """Balanced rotations of a walk with all four directions present."""
    rng = _v2_rng(seed, f'{difficulty}:displacement')
    # Include zero, cardinal, and diagonal displacements. All four directions
    # appear, so the original missing-opposite shortcut cannot solve this task.
    targets = [(0, 0), (2, 0), (1, 1), (2, 1), (1, -2)]
    dx, dy = targets[rng.below(len(targets))]
    padding = (2 if difficulty == 'medium' else 4) + rng.below(3)
    horizontal = ['east'] * (padding + max(dx, 0)) + ['west'] * (padding + max(-dx, 0))
    vertical = ['north'] * (padding + max(dy, 0)) + ['south'] * (padding + max(-dy, 0))
    steps = horizontal + vertical
    rng.shuffle(steps)
    choices = ['north', 'north-east', 'east', 'south-east', 'south',
               'south-west', 'west', 'north-west', 'same']

    def answer(x: int, y: int) -> str:
        if not x and not y:
            return 'same'
        vertical_part = 'north' if y > 0 else 'south' if y < 0 else ''
        horizontal_part = 'east' if x > 0 else 'west' if x < 0 else ''
        return '-'.join(part for part in (vertical_part, horizontal_part) if part)

    variants = []
    for rotation in range(4):
        rotated = [_DIRECTIONS[(_DIRECTIONS.index(d) + rotation) % 4] for d in steps]
        x, y = dx, dy
        for _ in range(rotation):
            x, y = y, -x
        variants.append(_probe('v2_spatial_displacement', 'spatial_reasoning', difficulty,
            {'movements': rotated, 'directions': choices,
             'rules': 'Направления постоянны; каждое перемещение равно одной клетке.'},
            'В каком направлении от начальной точки находится конечная? '
            'Для диагонали используйте north-east, south-east, south-west или north-west; '
            'для совпадающих точек — same.', answer(x, y)))
    _v2_rng(seed, f'{difficulty}:displacement:orientation-order').shuffle(variants)
    for i, probe in enumerate(variants, 1):
        probe['id'] = f'v2_spatial_displacement_{i}'
    return variants


def _v2_route(seed: str, difficulty: str) -> list[dict[str, Any]]:
    """Weighted cyclic map, with the reference obtained by Dijkstra's algorithm."""
    import heapq

    rng = _v2_rng(seed, f'{difficulty}:route')
    side = 4 if difficulty == 'medium' else 5
    positions = [(x, y) for y in range(side) for x in range(side)]
    edges: dict[tuple[int, int], dict[str, tuple[tuple[int, int], int]]] = {p: {} for p in positions}
    # A randomized spanning tree guarantees connectivity before cycles are added.
    visited = {positions[0]}
    stack = [positions[0]]
    while stack:
        x, y = stack[-1]
        candidates = [(direction, (x + vx, y + vy)) for direction, (vx, vy) in _VECTORS.items()
                      if (x + vx, y + vy) in edges and (x + vx, y + vy) not in visited]
        if not candidates:
            stack.pop()
            continue
        direction, other = candidates[rng.below(len(candidates))]
        cost = 1 + rng.below(9)
        edges[(x, y)][direction] = (other, cost)
        edges[other][_OPPOSITE[direction]] = ((x, y), cost)
        visited.add(other)
        stack.append(other)
    # Add cycles, retaining one shared weight for each pair of reverse edges.
    remaining = [(p, direction, (p[0] + vx, p[1] + vy))
                 for p in positions for direction, (vx, vy) in _VECTORS.items()
                 if direction in ('east', 'south') and (p[0] + vx, p[1] + vy) in edges
                 and direction not in edges[p]]
    rng.shuffle(remaining)
    for p, direction, other in remaining[:max(2, len(remaining) * 2 // 3)]:
        cost = 1 + rng.below(9)
        edges[p][direction] = (other, cost)
        edges[other][_OPPOSITE[direction]] = (p, cost)

    def distances(start: tuple[int, int]):
        dist = {start: 0}
        paths = {start: 1}
        route: dict[tuple[int, int], list[str]] = {start: []}
        queue = [(0, start)]
        while queue:
            distance, current = heapq.heappop(queue)
            if distance != dist[current]:
                continue
            for direction, (target, weight) in edges[current].items():
                candidate = distance + weight
                if candidate < dist.get(target, float('inf')):
                    dist[target] = candidate
                    paths[target] = paths[current]
                    route[target] = route[current] + [direction]
                    heapq.heappush(queue, (candidate, target))
                elif candidate == dist.get(target):
                    paths[target] = min(2, paths[target] + paths[current])
        return dist, paths, route

    choices = []
    for start in positions:
        if len(edges[start]) < 2:
            continue
        dist, paths, routes = distances(start)
        for dest in positions:
            if dest != start and paths.get(dest) == 1 and len(routes[dest]) >= 4:
                choices.append((dist[dest], start, dest, routes[dest]))
    if not choices:
        raise RuntimeError('no unique non-trivial weighted route')
    # Random selection from the longest weighted routes avoids a fixed endpoint.
    choices.sort(key=lambda item: item[0], reverse=True)
    _, start, dest, solution = choices[rng.below(min(10, len(choices)))]
    # Names remain unambiguous at both supported map sizes.
    labels = list(_ROOM_NAMES) + [f'Локация {i:02d}' for i in range(1, 10)]
    rng.shuffle(labels)
    names = {p: labels[i] for i, p in enumerate(positions)}
    variants = []
    for rotation in range(4):
        rooms = []
        for p in positions:
            exits = {_DIRECTIONS[(_DIRECTIONS.index(direction) + rotation) % 4]:
                     {'room': names[target], 'cost': cost}
                     for direction, (target, cost) in edges[p].items()}
            rooms.append({'room': names[p], 'exits': exits})
        _v2_rng(seed, f'{difficulty}:route:room-order:{rotation}').shuffle(rooms)
        first = _DIRECTIONS[(_DIRECTIONS.index(solution[0]) + rotation) % 4]
        variants.append(_probe('v2_spatial_route', 'spatial_reasoning', difficulty,
            {'observed_map': rooms, 'rules': 'Указаны все проходы; стоимость каждого прохода положительна. '
                                            'Все проходы обратимы и доступны.'},
            f'Вы находитесь в «{names[start]}». Какой первый выход ведёт в «{names[dest]}» '
            'маршрутом с наименьшей суммарной стоимостью? '
            'Ответьте одним из north, east, south, west.', first))
    _v2_rng(seed, f'{difficulty}:route:orientation-order').shuffle(variants)
    for i, probe in enumerate(variants, 1):
        probe['id'] = f'v2_spatial_route_{i}'
    return variants


def _v2_quests(seed: str, difficulty: str) -> list[dict[str, Any]]:
    """Several interleaved updates; queried updates are not always last."""
    rng = _v2_rng(seed, f'{difficulty}:quests')
    count = 6 if difficulty == 'medium' else 8
    people, items, places = list(_PEOPLE), list(_ITEMS), list(_PLACES)
    for values in (people, items, places):
        rng.shuffle(values)
    start_locations = places[:count]
    events = [f'{people[i]} просит найти {items[i]} в месте «{start_locations[i]}».' for i in range(count)]
    person_index = rng.below(count)
    location_index = (person_index + 1 + rng.below(count - 1)) % count
    updates = list(range(count))
    rng.shuffle(updates)
    target_position = updates.index(location_index)
    if target_position in (0, len(updates) - 1):
        updates[target_position], updates[len(updates) // 2] = updates[len(updates) // 2], updates[target_position]
    current = list(start_locations)
    # The queried quest changes twice, with other quests interleaved before
    # the last update. The latest matching event, not the first, is authoritative.
    first_options = [place for place in places if place != current[location_index]]
    current[location_index] = first_options[rng.below(len(first_options))]
    events.append(f'Изменение поручения: {people[location_index]} сообщает, что {items[location_index]} '
                  f'теперь находится в месте «{current[location_index]}».')
    for i in updates:
        options = [place for place in places if place != current[i]]
        current[i] = options[rng.below(len(options))]
        events.append(f'Изменение поручения: {people[i]} сообщает, что {items[i]} '
                      f'теперь находится в месте «{current[i]}».')
    history = {'history': events, 'rules': 'Показана вся история; более поздние изменения заменяют прежние сведения.'}
    return [
        _probe('v2_quest_assignment', 'quest_memory', difficulty, copy.deepcopy(history),
               f'Какой предмет попросил найти {people[person_index]}? Ответьте только названием предмета.',
               items[person_index]),
        _probe('v2_quest_update', 'quest_memory', difficulty, copy.deepcopy(history),
               f'Где сейчас нужно найти {items[location_index]} для персонажа {people[location_index]}? '
               'Ответьте только названием места.', current[location_index]),
    ]


def generate_suite_v2(seed: str | int, difficulty: str = 'medium') -> list[dict[str, Any]]:
    """Opt-in v2 suite; old generate_suite and saved v1 scores are unchanged.

    Returns four rotations each of two common-state spatial tasks plus two
    contextual quest tasks. Rotations of the same task remain correlated. The
    caller must record FIXED_PROBES_V2 and use fresh held-out evaluation seeds;
    never mix these scores with v1. public_probe strips private answer keys.
    """
    if not isinstance(seed, (str, int)) or isinstance(seed, bool):
        raise ValueError('seed must be a string or integer')
    if difficulty not in ('medium', 'hard'):
        raise ValueError('v2 difficulty must be medium or hard')
    value = str(seed)
    return [*_v2_displacement(value, difficulty), *_v2_route(value, difficulty),
            *_v2_quests(value, difficulty)]


# V3 is an opt-in research protocol. Each question uses an independently
# generated state, rather than rotations of one state; the shared seed still
# means that questions within one suite are clustered for statistical analysis.
FIXED_PROBES_V3 = 'fixed-probes-0.3.0'


def _v3_rng(seed: str, domain: str) -> _Stream:
    return _Stream(seed, f'{FIXED_PROBES_V3}:{domain}')


def _v3_walk(seed: str, index: int, target: str) -> dict[str, Any]:
    """Navigate 8–12 relative turns while tracking heading and displacement."""
    rng = _v3_rng(seed, f'walk:{index}')
    commands = ('forward', 'left', 'right', 'back')
    rotations = {'forward': 0, 'left': -1, 'right': 1, 'back': 2}
    vectors = {'north': (0, 1), 'east': (1, 0), 'south': (0, -1), 'west': (-1, 0)}
    for _ in range(10000):
        start_heading = rng.below(4)
        heading = start_heading
        steps = [commands[rng.below(4)] for _ in range(8 + rng.below(5))]
        x = y = 0
        visited_directions = set()
        for step in steps:
            heading = (heading + rotations[step]) % 4
            direction = _DIRECTIONS[heading]
            visited_directions.add(direction)
            dx, dy = vectors[direction]
            x, y = x + dx, y + dy
        direction = ('east' if x > 0 else 'west') if x and not y else (
            ('north' if y > 0 else 'south') if y and not x else None)
        if direction == target and len(visited_directions) == 4:
            return _probe(f'v3_spatial_walk_{index + 1}', 'spatial_reasoning', 'challenge',
                {'initial_heading': _DIRECTIONS[start_heading], 'steps': steps,
                 'rules': 'Перед каждым шагом поверните относительно текущего направления: '
                          'left на 90° влево, right на 90° вправо, back на 180°, '
                          'forward без поворота; затем пройдите одну клетку вперёд. '
                          'Север, восток, юг и запад постоянны.'},
                'В каком направлении от начальной точки находится конечная? '
                'Ответьте одним из north, east, south, west.', direction)
    raise RuntimeError('could not generate nontrivial relative walk')


def _v3_route(seed: str, index: int, target: str, first_edge_rank: int) -> dict[str, Any]:
    """Independent cyclic map with a unique minimum-cost 8–12 edge route."""
    import heapq

    rng = _v3_rng(seed, f'route:{index}')
    side = 7
    positions = [(x, y) for y in range(side) for x in range(side)]
    for _ in range(1000):
        edges: dict[tuple[int, int], dict[str, tuple[tuple[int, int], int]]] = {p: {} for p in positions}
        visited = {positions[0]}
        stack = [positions[0]]
        while stack:
            x, y = stack[-1]
            candidates = [(d, (x + dx, y + dy)) for d, (dx, dy) in _VECTORS.items()
                          if (x + dx, y + dy) in edges and (x + dx, y + dy) not in visited]
            if not candidates:
                stack.pop()
                continue
            direction, other = candidates[rng.below(len(candidates))]
            cost = 1 + rng.below(9)
            edges[(x, y)][direction] = (other, cost)
            edges[other][_OPPOSITE[direction]] = ((x, y), cost)
            visited.add(other)
            stack.append(other)
        remaining = [(p, d, (p[0] + dx, p[1] + dy))
                     for p in positions for d, (dx, dy) in _VECTORS.items()
                     if d in ('east', 'south') and (p[0] + dx, p[1] + dy) in edges and d not in edges[p]]
        rng.shuffle(remaining)
        for p, direction, other in remaining[:max(2, len(remaining) // 3)]:
            cost = 1 + rng.below(9)
            edges[p][direction] = (other, cost)
            edges[other][_OPPOSITE[direction]] = (p, cost)
        choices = []
        for start in positions:
            if len(edges[start]) != 4 or len({edge[1] for edge in edges[start].values()}) != 4:
                continue
            ranked = sorted(edges[start], key=lambda direction: (edges[start][direction][1], direction))
            if ranked.index(target) != first_edge_rank:
                continue
            distances, counts, routes = {start: 0}, {start: 1}, {start: []}
            queue = [(0, start)]
            while queue:
                cost, room = heapq.heappop(queue)
                if cost != distances[room]:
                    continue
                for direction, (nxt, weight) in edges[room].items():
                    new = cost + weight
                    if new < distances.get(nxt, float('inf')):
                        distances[nxt], counts[nxt] = new, counts[room]
                        routes[nxt] = routes[room] + [direction]
                        heapq.heappush(queue, (new, nxt))
                    elif new == distances.get(nxt):
                        counts[nxt] = min(2, counts[nxt] + counts[room])
            choices.extend((start, end, routes[end]) for end in positions
                           if end != start and counts.get(end) == 1
                           and 8 <= len(routes[end]) <= 12 and routes[end][0] == target)
        if choices:
            start, end, _ = choices[rng.below(len(choices))]
            labels = list(_ROOM_NAMES) + [f'Локация {i:02d}' for i in range(1, 34)]
            rng.shuffle(labels)
            names = {p: labels[i] for i, p in enumerate(positions)}
            rooms = [{'room': names[p], 'exits': {d: {'room': names[nxt], 'cost': cost}
                       for d, (nxt, cost) in edges[p].items()}} for p in positions]
            rng.shuffle(rooms)
            return _probe(f'v3_spatial_route_{index + 1}', 'spatial_reasoning', 'challenge',
                {'observed_map': rooms, 'rules': 'Указаны все проходы; каждый обратим и доступен. '
                                                'Стоимость каждого прохода положительна.'},
                f'Вы находитесь в «{names[start]}». Какой первый выход ведёт в «{names[end]}» '
                'путём с наименьшей суммарной стоимостью? '
                'Ответьте одним из north, east, south, west.', target)
    raise RuntimeError('could not generate long unique route for requested direction')


def _v3_quest(seed: str, index: int) -> dict[str, Any]:
    """Follow a queried item through four swaps and eight distractor swaps."""
    rng = _v3_rng(seed, f'quest:{index}')
    people, items = list(_PEOPLE), list(_ITEMS)
    rng.shuffle(people)
    rng.shuffle(items)
    holdings = dict(zip(people, items))
    initial = [{'person': person, 'item': holdings[person]} for person in people]
    rng.shuffle(initial)
    tracked_item = items[rng.below(len(items))]
    schedule = [True] * 4 + [False] * 8
    rng.shuffle(schedule)
    events = []
    for tracks in schedule:
        owner = next(p for p in people if holdings[p] == tracked_item)
        if tracks:
            other = [p for p in people if p != owner]
            left, right = owner, other[rng.below(len(other))]
        else:
            other = [p for p in people if p != owner]
            left = other.pop(rng.below(len(other)))
            right = other[rng.below(len(other))]
        if rng.below(2):
            left, right = right, left
        events.append({'action': 'swap', 'people': [left, right]})
        holdings[left], holdings[right] = holdings[right], holdings[left]
    owner = next(p for p in people if holdings[p] == tracked_item)
    if index % 2:
        question = f'Какой предмет находится у персонажа {owner} после всех обменов? Ответьте только названием предмета.'
        answer = tracked_item
    else:
        question = f'У кого находится {tracked_item} после всех обменов? Ответьте только именем персонажа.'
        answer = owner
    return _probe(f'v3_quest_swaps_{index + 1}', 'quest_memory', 'challenge',
                  {'initial_assignments': initial, 'events': events,
                   'rules': 'У каждого персонажа ровно один предмет. Каждый swap одновременно меняет '
                            'предметы указанных двух персонажей местами. Выполняйте обмены строго по порядку.'},
                  question, answer)


def generate_suite_v3(seed: str | int) -> list[dict[str, Any]]:
    """Generate an opt-in, independently-state-sampled challenge suite.

    Four relative walks, four 49-room weighted maps, and four quest histories
    use separate random streams. Walks and optimal routes have 8–12 transitions;
    direction answers are balanced per task family. Quest histories contain
    twelve dependent swaps. All questions are independent model requests; the
    four-per-seed structure is still clustered and must be analyzed by seed.
    Record FIXED_PROBES_V3, keep fresh held-out seeds private, strip answers
    with public_probe, and never combine scores with earlier protocol versions.
    """
    if not isinstance(seed, (str, int)) or isinstance(seed, bool):
        raise ValueError('seed must be a string or integer')
    value = str(seed)
    walks, routes = list(_DIRECTIONS), list(_DIRECTIONS)
    _v3_rng(value, 'walk:answer-order').shuffle(walks)
    _v3_rng(value, 'route:answer-order').shuffle(routes)
    ranks = list(range(4))
    _v3_rng(value, 'route:first-edge-rank-order').shuffle(ranks)
    return [*(_v3_walk(value, i, direction) for i, direction in enumerate(walks)),
            *(_v3_route(value, i, direction, ranks[i]) for i, direction in enumerate(routes)),
            *(_v3_quest(value, i) for i in range(4))]
