"""Independent v3-lite probes; does not modify the v1, v2, or v3 interfaces."""
from __future__ import annotations

from collections import deque
import heapq
import hashlib
from pathlib import Path

from benchmark.fixed_probes import (
    _DIRECTIONS, _OPPOSITE, _ROOM_NAMES, _Stream, _VECTORS, _probe,
    _v3_quest, _v3_walk, check_response, public_probe,
)

FIXED_PROBES_V3_LITE = 'fixed-probes-0.3-lite.2'


def source_fingerprint() -> str:
    """Fingerprint the lite generator and its shared v1/v3 helpers."""
    digest = hashlib.sha256()
    for path in (Path(__file__), Path(__file__).with_name('fixed_probes.py')):
        digest.update(path.name.encode('utf8') + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def _rng(seed: str, domain: str) -> _Stream:
    return _Stream(seed, f'{FIXED_PROBES_V3_LITE}:{domain}')


def _route(seed: str, index: int, target: str, target_rank: int):
    rng = _rng(seed, f'route:{index}')
    side = 5 + rng.below(2)
    positions = [(x, y) for y in range(side) for x in range(side)]
    for _ in range(5000):
        edges = {p: {} for p in positions}
        visited, stack = {positions[0]}, [positions[0]]
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
        missing = [(p, direction, (p[0] + dx, p[1] + dy))
                   for p in positions for direction, (dx, dy) in _VECTORS.items()
                   if direction in ('east', 'south') and (p[0] + dx, p[1] + dy) in edges
                   and direction not in edges[p]]
        rng.shuffle(missing)
        for p, direction, other in missing[:max(2, len(missing) * 2 // 3)]:
            cost = 1 + rng.below(9)
            edges[p][direction] = (other, cost)
            edges[other][_OPPOSITE[direction]] = (p, cost)
        choices = []
        for start in positions:
            if len(edges[start]) != 4 or len({v[1] for v in edges[start].values()}) != 4:
                continue
            ranked = sorted(edges[start], key=lambda d: (edges[start][d][1], d))
            if ranked.index(target) != target_rank:
                continue
            distance, ways, path = {start: 0}, {start: 1}, {start: []}
            queue = [(0, start)]
            while queue:
                cost, pos = heapq.heappop(queue)
                if cost != distance[pos]:
                    continue
                for direction, (nxt, weight) in edges[pos].items():
                    new = cost + weight
                    if new < distance.get(nxt, float('inf')):
                        distance[nxt], ways[nxt], path[nxt] = new, ways[pos], path[pos] + [direction]
                        heapq.heappush(queue, (new, nxt))
                    elif new == distance.get(nxt):
                        ways[nxt] = min(2, ways[nxt] + ways[pos])
            hops, first_steps = {start: 0}, {start: set()}
            pending = deque([start])
            while pending:
                pos = pending.popleft()
                for direction, (nxt, _) in edges[pos].items():
                    first = {direction} if pos == start else first_steps[pos]
                    if nxt not in hops:
                        hops[nxt] = hops[pos] + 1
                        first_steps[nxt] = set(first)
                        pending.append(nxt)
                    elif hops[nxt] == hops[pos] + 1:
                        first_steps[nxt].update(first)
            for end in positions:
                if end != start and ways.get(end) == 1 and 5 <= len(path[end]) <= 8 and path[end][0] == target:
                    # Every unweighted-shortest path must start differently.
                    if target not in first_steps[end]:
                        choices.append((start, end))
        if choices:
            start, end = choices[rng.below(len(choices))]
            labels = list(_ROOM_NAMES) + [f'Локация {i:02d}' for i in range(1, 34)]
            rng.shuffle(labels)
            names = {p: labels[i] for i, p in enumerate(positions)}
            rooms = [{'room': names[p], 'exits': {d: {'room': names[nxt], 'cost': cost}
                      for d, (nxt, cost) in edges[p].items()}} for p in positions]
            rng.shuffle(rooms)
            return _probe(f'v3_lite_spatial_route_{index + 1}', 'spatial_reasoning', 'challenge-lite',
                          {'observed_map': rooms, 'rules': 'Указаны все проходы; каждый обратим и доступен. '
                                                          'Стоимость каждого прохода положительна.'},
                          f'Вы находитесь в «{names[start]}». Какой первый выход ведёт в «{names[end]}» '
                          'путём с наименьшей суммарной стоимостью? '
                          'Ответьте одним из north, east, south, west.', target)
    raise RuntimeError('could not generate v3-lite route satisfying constraints')


def generate_suite_v3_lite(seed: str | int) -> list[dict]:
    """Four relative walks, four independent weighted maps, four swap chains.

    The answer directions and start-edge cost ranks are balanced within each
    seed. All 12 tasks require separate model requests, but are clustered by
    seed for analysis. Use public_probe before transmission.
    """
    if not isinstance(seed, (str, int)) or isinstance(seed, bool):
        raise ValueError('seed must be a string or integer')
    value = str(seed)
    walks, routes, ranks = list(_DIRECTIONS), list(_DIRECTIONS), list(range(4))
    _rng(value, 'walk:answer-order').shuffle(walks)
    _rng(value, 'route:answer-order').shuffle(routes)
    _rng(value, 'route:first-edge-rank-order').shuffle(ranks)
    # Distinct domain isolates these streams from v3 even for identical seeds.
    sub_seed = f'{FIXED_PROBES_V3_LITE}:{value}'
    result = []
    for index, answer in enumerate(walks):
        probe = _v3_walk(sub_seed, index, answer)
        probe.update(id=f'v3_lite_spatial_walk_{index+1}', difficulty='challenge-lite')
        result.append(probe)
    result.extend(_route(value, index, answer, ranks[index]) for index, answer in enumerate(routes))
    for index in range(4):
        probe = _v3_quest(sub_seed, index)
        probe.update(id=f'v3_lite_quest_swaps_{index+1}', difficulty='challenge-lite')
        result.append(probe)
    return result


__all__ = ['FIXED_PROBES_V3_LITE', 'generate_suite_v3_lite', 'source_fingerprint', 'public_probe', 'check_response']
