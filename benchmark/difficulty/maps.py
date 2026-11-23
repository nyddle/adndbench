"""Seeded maps for the configurable multi-region benchmark.

This module only generates a private world specification.  A game engine may
use its stable room IDs internally, but must not send the full map, room IDs,
site table or seed to a partially-observed player.  Terrain is a visible
location property, not a source of hidden movement rules.
"""
from __future__ import annotations

import hashlib
from typing import Any, MutableSequence

MAP_VERSION = "maps-1"
SIZES = (6, 8, 10)
TOPOLOGIES = ("winding", "mixed", "open")
DIRECTIONS = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}
OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east", "up": "down", "down": "up"}


class _Stream:
    """Versioned SHA-256 counter stream with unbiased bounded draws."""

    def __init__(self, seed: str, domain: str):
        self._seed = seed
        self._domain = domain
        self._counter = 0

    def below(self, n: int) -> int:
        if n <= 0:
            raise ValueError("empty range")
        limit = (1 << 256) - (1 << 256) % n
        while True:
            # Length-delimited components avoid ambiguous seed/domain encodings.
            payload = f"{MAP_VERSION}|{len(self._seed)}:{self._seed}|{self._domain}|{self._counter}"
            self._counter += 1
            value = int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest(), "big")
            if value < limit:
                return value % n

    def shuffle(self, values: MutableSequence[Any]) -> None:
        for i in range(len(values) - 1, 0, -1):
            j = self.below(i + 1)
            values[i], values[j] = values[j], values[i]


_ADJECTIVES = (
    "Янтарный", "Туманный", "Дальний", "Серебряный", "Сумрачный", "Тихий",
    "Лунный", "Каменный", "Зелёный", "Ветреный", "Солнечный", "Снежный",
)
_NOUNS = (
    "холм", "путь", "брод", "лес", "предел", "ключ", "поворот", "дол",
    "исток", "склон", "пруд", "перевал",
)
_REGION_CONFIGS = (
    ("overworld", "Открытые земли", None),
    ("mountain", "Гора", 3),
    ("tower", "Башня мага", 2),
    ("dungeon", "Подземелье", 3),
)
# Terrain categories are descriptive only; encounter and quest systems decide
# any mechanics and receive their own independent seed streams.
_TERRAINS = {
    "overworld": ("равнина", "лес", "руины", "болото", "холмы"),
    "mountain": ("горная тропа", "скалы", "перевал"),
    "tower": ("зал башни", "мастерская", "библиотека"),
    "dungeon": ("коридор подземелья", "склеп", "пещера"),
}


def _room_id(zone: str, x: int, y: int) -> str:
    return f"{zone}-{x}-{y}"


def _make_region(zone: str, prefix: str, side: int, seed: str,
                 topology: str, terrain_diversity: int) -> list[dict[str, Any]]:
    names = [f"{prefix}: {adjective} {noun}" for adjective in _ADJECTIVES for noun in _NOUNS]
    name_rng = _Stream(seed, f"names:{zone}")
    name_rng.shuffle(names)
    terrain_rng = _Stream(seed, f"terrain:{zone}")
    terrains = _TERRAINS[zone][:terrain_diversity]
    rooms = [
        {"id": _room_id(zone, x, y), "name": names[y * side + x], "zone": zone,
         "terrain": terrains[terrain_rng.below(len(terrains))], "exits": {}}
        for y in range(side) for x in range(side)
    ]
    by_id = {room["id"]: room for room in rooms}
    rng = _Stream(seed, f"layout:{zone}")
    seen = {(0, 0)}
    stack = [(0, 0)]
    while stack:
        x, y = stack[-1]
        candidates = []
        for direction, (dx, dy) in DIRECTIONS.items():
            nx, ny = x + dx, y + dy
            if 0 <= nx < side and 0 <= ny < side and (nx, ny) not in seen:
                candidates.append((direction, nx, ny))
        if not candidates:
            stack.pop()
            continue
        direction, nx, ny = candidates[rng.below(len(candidates))]
        here, there = by_id[_room_id(zone, x, y)], by_id[_room_id(zone, nx, ny)]
        here["exits"][direction] = there["id"]
        there["exits"][OPPOSITE[direction]] = here["id"]
        seen.add((nx, ny))
        stack.append((nx, ny))

    # Additional paths preserve simple cardinal geometry and create loops.
    walls = []
    for y in range(side):
        for x in range(side):
            for direction in ("east", "south"):
                dx, dy = DIRECTIONS[direction]
                nx, ny = x + dx, y + dy
                here = by_id[_room_id(zone, x, y)]
                if nx < side and ny < side and direction not in here["exits"]:
                    walls.append((here["id"], direction, _room_id(zone, nx, ny)))
    rng.shuffle(walls)
    # Avoid a forced long maze on a map labelled "open".  All regions stay
    # connected at every level because the spanning tree is never removed.
    extras = {"winding": len(walls) // 8, "mixed": len(walls) // 2, "open": len(walls)}[topology]
    for source, direction, target in walls[:extras]:
        by_id[source]["exits"][direction] = target
        by_id[target]["exits"][OPPOSITE[direction]] = source
    return rooms


def generate_map(seed: str | int, size: int = 6, *, topology: str = "mixed",
                 terrain_diversity: int = 2) -> dict[str, Any]:
    """Return a deterministic private world spec with stable string IDs.

    ``size`` selects the side length of the overworld; mountain, tower and
    dungeon are 3x3, 2x2 and 3x3 respectively. ``topology`` changes the
    density of local paths, and ``terrain_diversity`` selects 1 to 3 cosmetic
    terrain types per region.  None of these values alter encounter, quest,
    character, or NPC generator streams. The returned IDs, exits and sites are
    evaluator-only. Sites are disjoint and all are reachable from ``elder``.

    Changing only terrain diversity leaves names, edges and sites unchanged.
    Changing only topology leaves names, terrain and sites unchanged. Integer
    and string representations of a seed intentionally denote the same world,
    matching the classic engine. Generator changes require a MAP_VERSION bump.
    """
    if not isinstance(seed, (str, int)) or isinstance(seed, bool):
        raise ValueError("seed must be a string or integer")
    if not isinstance(size, int) or isinstance(size, bool) or size not in SIZES:
        raise ValueError("size must be one of 6, 8, or 10")
    if not isinstance(topology, str) or topology not in TOPOLOGIES:
        raise ValueError("topology must be winding, mixed, or open")
    if not isinstance(terrain_diversity, int) or isinstance(terrain_diversity, bool) or terrain_diversity not in (1, 2, 3):
        raise ValueError("terrain_diversity must be 1, 2, or 3")
    seed_text = str(seed)
    regions: dict[str, list[dict[str, Any]]] = {}
    for zone, prefix, fixed_size in _REGION_CONFIGS:
        regions[zone] = _make_region(zone, prefix, size if fixed_size is None else fixed_size,
                                     seed_text, topology, terrain_diversity)
    rooms = [room for zone, _, _ in _REGION_CONFIGS for room in regions[zone]]
    by_id = {room["id"]: room for room in rooms}
    elder = regions["overworld"][0]["id"]
    by_id[elder]["name"] = "Деревня: Янтарный очаг"
    by_id[elder]["terrain"] = "деревня"

    # Assign the region links and important sites to distinct, seed-chosen
    # cells; separate streams prevent geometry/terrain tweaks moving them.
    selected = {}
    for zone, _, _ in _REGION_CONFIGS:
        ids = [room["id"] for room in regions[zone]]
        if zone == "overworld":
            ids.remove(elder)
        _Stream(seed_text, f"sites:{zone}").shuffle(ids)
        selected[zone] = ids
    land, mountain, tower, dungeon = (selected[z] for z in ("overworld", "mountain", "tower", "dungeon"))
    sites = {
        "elder": elder, "mountain_gate": land[0], "dungeon_gate": land[1],
        "herbalist": land[2], "bandit": land[3],
        "mountain_entry": mountain[0], "tower_gate": mountain[1], "herb": mountain[2], "guard": mountain[3],
        "tower_entry": tower[0], "wizard": tower[1],
        "dungeon_entry": dungeon[0], "dragon": dungeon[1],
    }
    for start, direction, end in (
        ("mountain_gate", "up", "mountain_entry"),
        ("tower_gate", "up", "tower_entry"),
        ("dungeon_gate", "down", "dungeon_entry"),
    ):
        source, target = by_id[sites[start]], by_id[sites[end]]
        source["exits"][direction] = target["id"]
        target["exits"][OPPOSITE[direction]] = source["id"]
    return {"version": MAP_VERSION, "config": {"size": size, "topology": topology,
            "terrain_diversity": terrain_diversity}, "rooms": rooms, "sites": sites}
