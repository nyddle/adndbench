"""Deterministic combat encounters and telegraphed enemy responses.

This module owns no mutable game state. The caller stores each encounter's HP
and phase, supplies only the current intent to the player, and advances the
phase after a surviving enemy responds. Placement uses an independent
versioned stream; it never changes the supplied map.
"""
from __future__ import annotations

import hashlib
import json
from collections import deque
from typing import Any, Iterable, Mapping

COMBAT_VERSION = "combat-1"
DIFFICULTY_COUNTS = {"easy": 2, "medium": 4, "hard": 6}
_DIFFICULTY_BONUS = {"easy": 0, "medium": 1, "hard": 2}
ENEMIES = {
    "raider": {"name": "разбойник", "hp": 6},
    "sentinel": {"name": "бронированный страж", "hp": 8},
    "wisp": {"name": "грозовой дух", "hp": 6},
    "dragon": {"name": "дракон", "hp": 16},
}
DEFAULT_TYPES = ("raider", "sentinel", "wisp")

# An encounter has one response per valid attack, defence, potion, or usable
# combat ability. Blocking applies to the player's hit BEFORE the response.
_PHASES = {
    "raider": (
        {"id": "slash", "name": "удар клинком", "damage": 2, "cap": None,
         "description": "Разбойник наносит 2 урона."},
        {"id": "lunge", "name": "выпад", "damage": 4, "cap": None,
         "description": "Разбойник готовит выпад на 4 урона."},
    ),
    "sentinel": (
        {"id": "guard", "name": "блок щитом", "damage": 1, "cap": 1,
         "description": "Страж блокирует: физический удар наносит не более 1 урона, огонь действует полностью; ответ — 1 урона."},
        {"id": "slam", "name": "тяжёлый удар", "damage": 4, "cap": None,
         "description": "Страж открывается и готовит удар на 4 урона; броня не ограничивает атаку."},
    ),
    "wisp": (
        {"id": "charge", "name": "заряд молнии", "damage": 0, "cap": None,
         "description": "Дух заряжает молнию, в этот ход ответного урона нет."},
        {"id": "burst", "name": "разряд молнии", "damage": 5, "cap": None,
         "description": "Дух выпускает молнию на 5 урона."},
    ),
    "dragon": (
        {"id": "breath", "name": "огненное дыхание", "damage": 6, "cap": None,
         "description": "Дракон дышит огнём на 6 урона; оберег снижает урон на 2."},
        {"id": "claws", "name": "удар когтями", "damage": 2, "cap": None,
         "description": "Дракон готовит удар когтями на 2 урона."},
    ),
}

COMBAT_RULES = (
    "В бою у врага показано текущее намерение и его последствия до вашего действия. "
    "Атака, защита, зелье и разрешённая боевая способность дают живому врагу ответ; "
    "убитый враг не отвечает. После каждого ответа враг переходит к следующей фазе. "
    "Защита снижает ответный урон до не более 1 и усиливает следующую обычную атаку; "
    "если намерение не наносит урон, защита также стоит 0 HP. "
    "Страж в фазе блока ограничивает физический урон; огненная устойчивость "
    "и размер каждого ограничения указаны в текущем намерении. "
    "рунический оберег снижает только дыхание дракона на 2."
)


def _phase(kind: str, phase: int, difficulty: str = "easy") -> dict[str, Any]:
    if kind not in _PHASES:
        raise ValueError(f"unknown enemy kind: {kind}")
    if not isinstance(phase, int) or isinstance(phase, bool) or phase < 0:
        raise ValueError("phase must be a non-negative integer")
    if not isinstance(difficulty, str) or difficulty not in DIFFICULTY_COUNTS:
        raise ValueError("difficulty must be easy, medium, or hard")
    phases = _PHASES[kind]
    state = dict(phases[phase % len(phases)])
    state["damage"] += _DIFFICULTY_BONUS[difficulty]
    state["fire_cap"] = None
    if kind == "sentinel" and state["id"] == "guard":
        # Harder shields change the tactical choice, not just enemy HP.
        state["fire_cap"] = {"easy": None, "medium": 2, "hard": 1}[difficulty]
    if difficulty != "easy":
        if state["fire_cap"] is not None:
            resistance = f"; физический урон не более {state['cap']}, огненный не более {state['fire_cap']}"
        else:
            resistance = ""
        ward = "; оберег снижает урон дыхания на 2" if kind == "dragon" and state["id"] == "breath" else ""
        state["description"] = (f"{ENEMIES[kind]['name']}: {state['name']}; "
                                f"ответ — {state['damage']} урона{resistance}{ward}.")
    return state


def incoming(kind: str, phase: int, *, ward: bool = False, defending: bool = False,
             difficulty: str = "easy") -> int:
    """HP lost from one response, if this enemy survives the player's action."""
    state = _phase(kind, phase, difficulty)
    damage = state["damage"]
    if ward and kind == "dragon" and state["id"] == "breath":
        damage = max(0, damage - 2)
    return min(damage, 1) if defending else damage


def apply_hit(kind: str, phase: int, damage: int, *, damage_type: str = "physical",
              difficulty: str = "easy") -> int:
    """Return actual enemy HP damage after phase resistance, without mutation."""
    state = _phase(kind, phase, difficulty)
    if not isinstance(damage, int) or isinstance(damage, bool) or damage < 0:
        raise ValueError("damage must be a non-negative integer")
    if damage_type not in ("physical", "fire"):
        raise ValueError("damage_type must be physical or fire")
    cap = state["cap"] if damage_type == "physical" else state["fire_cap"]
    return min(damage, cap) if cap is not None else damage


def intent(kind: str, phase: int, *, ward: bool = False, difficulty: str = "easy") -> dict[str, Any]:
    """Return the CURRENT public, actionable intent; no future phase or map data."""
    state = _phase(kind, phase, difficulty)
    return {
        "id": state["id"], "name": state["name"], "description": state["description"],
        "damage": incoming(kind, phase, ward=ward, difficulty=difficulty),
        "damage_if_defending": incoming(kind, phase, ward=ward, defending=True, difficulty=difficulty),
        "physical_damage_cap": state["cap"],
        "fire_damage_cap": state["fire_cap"],
    }


def _rank(seed: str, label: str) -> str:
    raw = json.dumps([COMBAT_VERSION, seed, label], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf8")).hexdigest()


def _validate_world(world: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    try:
        rooms, sites = world["rooms"], world["sites"]
    except (KeyError, TypeError):
        raise ValueError("world must contain rooms and sites") from None
    if not isinstance(rooms, list) or not rooms or not isinstance(sites, dict):
        raise ValueError("world must contain a nonempty room list and sites map")
    by_id: dict[str, dict[str, Any]] = {}
    for room in rooms:
        if not isinstance(room, dict) or not isinstance(room.get("id"), str) or not room["id"]:
            raise ValueError("room ids must be nonempty strings")
        if room["id"] in by_id or not isinstance(room.get("exits"), dict):
            raise ValueError("duplicate room id or invalid exits")
        by_id[room["id"]] = room
    if "elder" not in sites or "dragon" not in sites or any(v not in by_id for v in sites.values()):
        raise ValueError("site references must name existing rooms, including elder and dragon")
    for room in rooms:
        if any(dest not in by_id for dest in room["exits"].values()):
            raise ValueError("exit references unknown room")
    return by_id, sites


def _protected_connected(rooms: Mapping[str, Mapping[str, Any]], protected: set[str], blocked: set[str], start: str) -> bool:
    if start in blocked:
        return False
    queue = deque([start])
    seen = {start}
    while queue:
        room = queue.popleft()
        for destination in rooms[room]["exits"].values():
            if destination not in blocked and destination not in seen:
                seen.add(destination)
                queue.append(destination)
    return protected <= seen


def generate_encounters(
    seed: str | int,
    world: Mapping[str, Any],
    difficulty: str = "easy",
    *,
    extra_count: int | None = None,
    enemy_types: Iterable[str] = DEFAULT_TYPES,
    reserved_room_ids: Iterable[str] = (),
) -> dict[str, dict[str, Any]]:
    """Produce deterministic room-ID keyed encounter state, with no mutation.

    The boss is always at sites['dragon']. Extras avoid every site and every
    caller-supplied reserved ID (including generated quest sites). Placing them
    never disconnects the protected rooms if those extras are treated as
    blocked. Fewer than requested may be returned when no safe sites remain;
    the actual count is ``len(result) - 1``. Encounter kinds for existing
    placements do not change when only the requested count changes.
    """
    if not isinstance(seed, (int, str)) or isinstance(seed, bool):
        raise ValueError("seed must be a string or integer")
    if not isinstance(difficulty, str) or difficulty not in DIFFICULTY_COUNTS:
        raise ValueError("difficulty must be easy, medium, or hard")
    count = DIFFICULTY_COUNTS[difficulty] if extra_count is None else extra_count
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise ValueError("extra_count must be a non-negative integer")
    types = tuple(enemy_types)
    if not types or any(t not in DEFAULT_TYPES for t in types) or len(set(types)) != len(types):
        raise ValueError("enemy_types must be distinct ordinary enemy kinds")
    rooms, sites = _validate_world(world)
    reserved = set(reserved_room_ids)
    if any(room not in rooms for room in reserved):
        raise ValueError("reserved_room_ids contains unknown room")
    dragon = sites["dragon"]
    protected = set(sites.values()) | reserved
    if not _protected_connected(rooms, protected, set(), sites["elder"]):
        raise ValueError("protected sites are disconnected")
    candidates = sorted((room for room in rooms if room not in protected),
                        key=lambda room: (_rank(str(seed), "room:" + room), room))
    blocked: set[str] = set()
    encounters = {dragon: {"kind": "dragon", "name": ENEMIES["dragon"]["name"],
                           "hp": ENEMIES["dragon"]["hp"], "phase": 0,
                           "difficulty": difficulty}}
    for room in candidates:
        if len(blocked) >= count:
            break
        if not _protected_connected(rooms, protected, blocked | {room}, sites["elder"]):
            continue
        blocked.add(room)
        # Selecting by room rather than list index keeps types stable across
        # count changes and additions/removals of unrelated candidates.
        index = int(_rank(str(seed), "type:" + room), 16) % len(types)
        kind = types[index]
        encounters[room] = {"kind": kind, "name": ENEMIES[kind]["name"],
                            "hp": ENEMIES[kind]["hp"], "phase": 0,
                            "difficulty": difficulty}
    return encounters
