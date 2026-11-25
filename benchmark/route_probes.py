"""Shortest-path probes built only from observed successful movements.

Answers come from the agent-visible graph, never from hidden world state. A
reverse edge is used only when the opposite exit was itself visible in the
destination observation, so probes stay correct even for one-way passages.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Mapping, Sequence

from benchmark.probes import check_answer, public_probe

__all__ = ['build_route_probes', 'public_probe', 'check_answer']

_OPPOSITE = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east',
             'up': 'down', 'down': 'up'}


def _observed_graph(trace: Sequence[Mapping[str, Any]],
                    final_observation: Mapping[str, Any]) -> tuple[dict[str, dict[str, str]], list[str]]:
    edges: dict[str, dict[str, str]] = {}
    order: list[str] = []

    def note(room: str) -> None:
        if room not in edges:
            edges[room] = {}
            order.append(room)

    for index, turn in enumerate(trace):
        if not isinstance(turn, Mapping):
            continue
        obs, action = turn.get('observation'), turn.get('action')
        if not isinstance(obs, Mapping) or not isinstance(action, Mapping):
            continue
        if action.get('type') != 'move':
            continue
        direction = action.get('direction')
        following = (trace[index + 1].get('observation', {})
                     if index + 1 < len(trace) else final_observation)
        if not isinstance(following, Mapping):
            continue
        origin, destination = obs.get('room'), following.get('room')
        if not (isinstance(origin, str) and origin and isinstance(destination, str) and destination
                and isinstance(direction, str) and direction in _OPPOSITE):
            continue
        if origin == destination or direction not in obs.get('exits', []):
            continue
        note(origin)
        note(destination)
        edges[origin][direction] = destination
        # The way back counts only when the model actually saw the opposite exit.
        reverse = _OPPOSITE[direction]
        if reverse in (following.get('exits') or []):
            edges[destination][reverse] = origin
    return edges, order


def _bfs(edges: Mapping[str, Mapping[str, str]], start: str):
    dist = {start: 0}
    paths = {start: 1}
    first: dict[str, str] = {}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for direction, nxt in edges.get(current, {}).items():
            if nxt not in dist:
                dist[nxt] = dist[current] + 1
                paths[nxt] = paths[current]
                first[nxt] = direction if current == start else first[current]
                queue.append(nxt)
            elif dist[nxt] == dist[current] + 1:
                paths[nxt] = min(2, paths[nxt] + paths[current])
    return dist, paths, first


def build_route_probes(trace: Sequence[Mapping[str, Any]], final_observation: Mapping[str, Any], *,
                       min_distance: int = 4, max_probes: int = 3, min_exits: int = 1) -> list[dict[str, str]]:
    """First-exit questions about uniquely shortest paths in the observed graph.

    Pairs closer than ``min_distance`` or with several shortest paths are
    skipped, so the correct first exit is always unambiguous. Start rooms with
    fewer than ``min_exits`` observed exits are skipped: with two known exits a
    coin flip is already half right. Fewer (or zero) probes are produced when
    the trace contains no suitable pair.
    """
    if not isinstance(min_distance, int) or isinstance(min_distance, bool) or min_distance < 2:
        raise ValueError('min_distance must be an integer of at least 2')
    if not isinstance(max_probes, int) or isinstance(max_probes, bool) or max_probes < 0:
        raise ValueError('max_probes must be a non-negative integer')
    if not isinstance(min_exits, int) or isinstance(min_exits, bool) or min_exits < 1:
        raise ValueError('min_exits must be a positive integer')
    edges, order = _observed_graph(trace, final_observation)
    probes: list[dict[str, str]] = []
    used: set[tuple[str, str]] = set()
    # One probe per start room: questions about a single origin would be
    # correlated and often share the same first exit.
    for start in order:
        if len(probes) >= max_probes:
            break
        if len(edges[start]) < min_exits:
            continue
        dist, paths, first = _bfs(edges, start)
        for destination in order:
            if len(probes) >= max_probes:
                break
            if destination == start or (start, destination) in used:
                continue
            if dist.get(destination, 0) < min_distance or paths.get(destination, 0) != 1:
                continue
            used.add((start, destination))
            probes.append({
                'id': f'route_planning_{len(probes) + 1}',
                'capability': 'route_planning',
                'question': (f'Вы исследовали местность и помните комнаты «{start}» и «{destination}». '
                             f'Каким направлением нужно выйти из «{start}», чтобы попасть '
                             f'в «{destination}» кратчайшим из виденных маршрутов? '
                             'Ответьте одним направлением на английском.'),
                'answer': first[destination],
            })
            break
    return probes
