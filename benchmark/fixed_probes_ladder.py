"""Development-only fixed-probe complexity ladder.

These probes are opt-in and independent of the released protocols.  The
levels describe construction, not observed difficulty for any given model.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from benchmark.fixed_probes import (
    _DIRECTIONS, _ITEMS, _PEOPLE, _Stream, _probe, check_response, public_probe,
)

VERSION = 'fixed-probes-ladder-0.1.0'
LEVELS = {'standard': (12, 12, 4), 'extended': (24, 24, 8), 'long': (48, 48, 16)}


def source_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in (Path(__file__), Path(__file__).with_name('fixed_probes.py')):
        digest.update(path.name.encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def _rng(seed: str, level: str, domain: str) -> _Stream:
    return _Stream(seed, f'{VERSION}:{level}:{domain}')


def _walk(seed: str, level: str, index: int, target: str, length: int) -> dict:
    rng = _rng(seed, level, f'walk:{index}')
    commands = ('forward', 'left', 'right', 'back')
    turns = {'forward': 0, 'left': -1, 'right': 1, 'back': 2}
    vectors = ((0, 1), (1, 0), (0, -1), (-1, 0))
    for _ in range(10000):
        initial = rng.below(4)
        heading, x, y = initial, 0, 0
        steps = [commands[rng.below(4)] for _ in range(length)]
        seen = set()
        for step in steps:
            heading = (heading + turns[step]) % 4
            seen.add(heading)
            dx, dy = vectors[heading]
            x, y = x + dx, y + dy
        answer = ('east' if x > 0 else 'west') if x and not y else (
            ('north' if y > 0 else 'south') if y and not x else None)
        if answer == target and len(seen) == 4:
            return _probe(f'ladder_walk_{index + 1}', 'spatial_reasoning', level,
                {'initial_heading': _DIRECTIONS[initial], 'steps': steps,
                 'rules': 'Перед каждым шагом поверните относительно текущего направления: '
                          'left на 90° влево, right на 90° вправо, back на 180°, '
                          'forward без поворота; затем пройдите одну клетку вперёд. '
                          'Север, восток, юг и запад постоянны.'},
                'В каком направлении от начальной точки находится конечная? '
                'Ответьте одним из north, east, south, west.', answer)
    raise RuntimeError('could not construct a ladder walk')


def _swaps(seed: str, level: str, index: int, length: int, target_swaps: int) -> dict:
    rng = _rng(seed, level, f'swaps:{index}')
    people, items = list(_PEOPLE), list(_ITEMS)
    rng.shuffle(people)
    rng.shuffle(items)
    holdings = dict(zip(people, items))
    initial = [{'person': person, 'item': holdings[person]} for person in people]
    rng.shuffle(initial)
    item = items[rng.below(len(items))]
    schedule = [True] * target_swaps + [False] * (length - target_swaps)
    rng.shuffle(schedule)
    events = []
    for involves_target in schedule:
        owner = next(person for person in people if holdings[person] == item)
        others = [person for person in people if person != owner]
        if involves_target:
            a, b = owner, others[rng.below(len(others))]
        else:
            a = others.pop(rng.below(len(others)))
            b = others[rng.below(len(others))]
        if rng.below(2):
            a, b = b, a
        events.append({'action': 'swap', 'people': [a, b]})
        holdings[a], holdings[b] = holdings[b], holdings[a]
    owner = next(person for person in people if holdings[person] == item)
    return _probe(f'ladder_swaps_{index + 1}', 'quest_memory', level,
        {'initial_assignments': initial, 'events': events,
         'rules': 'У каждого персонажа ровно один предмет. Каждый swap одновременно меняет '
                  'предметы указанных двух персонажей местами. Выполняйте обмены строго по порядку.'},
        f'У кого находится {item} после всех обменов? Ответьте только именем персонажа.', owner)


def generate_suite(seed: str | int, level: str) -> list[dict]:
    """Generate 4 relative walks and 4 item-owner questions for one dev world.

    Different levels are independent task sets, not matched variants; record
    the level, source fingerprint and seed privately. Strip private answers
    with public_probe before sending any question to a model.
    """
    if not isinstance(seed, (str, int)) or isinstance(seed, bool):
        raise ValueError('seed must be a string or integer')
    if level not in LEVELS:
        raise ValueError('unknown ladder level')
    value = str(seed)
    walk_length, event_count, target_swaps = LEVELS[level]
    targets = list(_DIRECTIONS)
    _rng(value, level, 'walk:answer-order').shuffle(targets)
    return [*(_walk(value, level, i, target, walk_length) for i, target in enumerate(targets)),
            *(_swaps(value, level, i, event_count, target_swaps) for i in range(4))]


__all__ = ['VERSION', 'LEVELS', 'generate_suite', 'source_fingerprint', 'public_probe', 'check_response']
