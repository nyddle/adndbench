"""Observation-only baseline for the multi-region adventure.

This agent maintains its own graph from the transitions it has actually seen.
It never imports the game engine or reads world state. It is a smoke-test and
reference policy, not an optimal solver or a proxy for language models.
"""
from __future__ import annotations

from collections import deque
import re
from typing import Any

_OPPOSITE = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east',
             'up': 'down', 'down': 'up'}


class RealmsBaselineAgent:
    """Remember visible rooms and try previously communicated objectives."""

    def __init__(self) -> None:
        self.graph: dict[str, dict[str, str]] = {}
        self.exits: dict[str, list[str]] = {}
        self.previous_room: str | None = None
        self.previous_direction: str | None = None
        self.refuge: str | None = None
        self.spoken: dict[str, tuple[str, ...]] = {}
        self.searches: set[tuple[str, int]] = set()
        self.quests: dict[str, tuple[str, str]] = {}
        self.completed: set[str] = set()
        self.wizard_room: str | None = None
        self.wizard_visited = False

    def _remember_transition(self, room: str) -> None:
        self.graph.setdefault(room, {})
        if self.previous_room is not None and self.previous_direction and room != self.previous_room:
            self.graph.setdefault(self.previous_room, {})[self.previous_direction] = room
            opposite = _OPPOSITE.get(self.previous_direction)
            if opposite:
                self.graph[room][opposite] = self.previous_room
        self.previous_room = self.previous_direction = None

    def _first_step(self, room: str, destinations: set[str]) -> str | None:
        queue = deque([(room, None)])
        visited = {room}
        while queue:
            current, first = queue.popleft()
            if first is not None and current in destinations:
                return first
            for direction in self.exits.get(current, []):
                destination = self.graph.get(current, {}).get(direction)
                if destination is not None and destination not in visited:
                    visited.add(destination)
                    queue.append((destination, first or direction))
        return None

    def _frontier_step(self, room: str) -> str | None:
        queue = deque([(room, None)])
        visited = {room}
        while queue:
            current, first = queue.popleft()
            for direction in self.exits.get(current, []):
                destination = self.graph.get(current, {}).get(direction)
                if destination is None:
                    return first or direction
                if destination not in visited:
                    visited.add(destination)
                    queue.append((destination, first or direction))
        return None

    def _move(self, room: str, direction: str) -> dict[str, Any]:
        self.previous_room, self.previous_direction = room, direction
        return {'type': 'move', 'direction': direction}

    def act(self, obs: dict[str, Any]) -> dict[str, Any]:
        room = obs['room']
        if self.refuge is None:
            self.refuge = room
        self._remember_transition(room)
        self.exits[room] = list(obs.get('exits', []))
        message = str(obs.get('message', ''))
        match = re.search(r'найдите (.+?) в месте «(.+?)» и принесите мне сюда, в «(.+?)»', message)
        if match:
            item, target, giver_room = match.groups()
            self.quests[item] = target, giver_room
        wizard_match = re.search(r'маг в башне, в месте «(.+?)»', message)
        if wizard_match:
            self.wizard_room = wizard_match.group(1)
        completed_match = re.search(r'принимает (.+?)\. Поручение выполнено', message)
        if completed_match:
            self.completed.add(completed_match.group(1))
        inventory = tuple(sorted(obs.get('inventory', [])))
        if obs.get('npc') == 'Маг' and 'рунический оберег' in inventory:
            self.wizard_visited = True

        enemy = obs.get('enemy')
        if enemy:
            if enemy.get('intent') == 'огненное дыхание':
                return {'type': 'defend'}
            if obs.get('potions', 0) and obs.get('hp', 0) <= 8:
                return {'type': 'potion'}
            return {'type': 'attack'}
        if room == self.refuge and obs.get('rations', 0) and obs.get('hp', 0) <= 9:
            return {'type': 'rest'}
        if obs.get('npc') and self.spoken.get(room) != inventory:
            self.spoken[room] = inventory
            return {'type': 'talk'}
        for item, (target, _) in self.quests.items():
            search_key = (room, len(self.quests))
            ready = item != 'сердце звезды' or 'рунический оберег' in inventory
            if ready and item not in self.completed and item not in inventory and target == room and search_key not in self.searches:
                self.searches.add(search_key)
                return {'type': 'search'}

        # Finish carried quests first; otherwise favour the wizard, then known targets.
        carried = {giver for item, (_, giver) in self.quests.items()
                   if item in inventory and item not in self.completed}
        direction = self._first_step(room, carried)
        if direction:
            return self._move(room, direction)
        if self.wizard_room and not self.wizard_visited:
            direction = self._first_step(room, {self.wizard_room})
            if direction:
                return self._move(room, direction)
        targets = {target for item, (target, _) in self.quests.items()
                   if item not in inventory and item not in self.completed
                   and (item != 'сердце звезды' or 'рунический оберег' in inventory)}
        direction = self._first_step(room, targets)
        if direction:
            return self._move(room, direction)
        direction = self._frontier_step(room)
        if direction:
            return self._move(room, direction)
        if self.exits[room]:
            return self._move(room, self.exits[room][0])
        return {'type': 'search'}
