"""Deterministic, observable character classes for the configurable scenario.

This module owns no world state.  ``use_ability`` only returns a new character
state and a declarative effect; the game is responsible for applying the effect,
resolving a surviving opponent's response and consuming the action's turn.  This
keeps the same rules usable by an agent, the simulator, and an evaluator.

A game action selects an ability as ``{"type": "ability", "ability": ID}``.
The initial pool of energy is finite; this module never restores it implicitly.
Call ``advance_turn`` after every turn, including invalid ones.  Pass the
successfully used ID as ``used_ability_id`` so its newly set cooldown does not
immediately tick down.  A cooldown of N therefore blocks N subsequent turns.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


# These descriptions are public rules, not hints based on hidden world state.
_PROFILES: dict[str, dict[str, Any]] = {
    "generalist": {
        "name": "Искатель приключений",
        "max_energy": 6,
        "ability": {
            "id": "first_aid",
            "name": "Первая помощь",
            "description": "Восстанавливает до 5 HP; в бою выживший противник отвечает.",
            "energy_cost": 2,
            "cooldown_turns": 3,
            "context": "injured",
            "effect": {"heal": 5},
        },
    },
    "warrior": {
        "name": "Воин",
        "max_energy": 6,
        "ability": {
            "id": "heavy_strike",
            "name": "Тяжёлый удар",
            "description": "Наносит 6 физического урона врагу; выживший противник отвечает.",
            "energy_cost": 2,
            "cooldown_turns": 2,
            "context": "combat",
            "effect": {"damage": 6, "damage_type": "physical"},
        },
    },
    "mage": {
        "name": "Маг",
        "max_energy": 6,
        "ability": {
            "id": "fire_bolt",
            "name": "Огненная стрела",
            "description": "Наносит 7 огненного урона врагу; выживший противник отвечает.",
            "energy_cost": 3,
            "cooldown_turns": 2,
            "context": "combat",
            "effect": {"damage": 7, "damage_type": "fire"},
        },
    },
    "scout": {
        "name": "Разведчик",
        "max_energy": 6,
        "ability": {
            "id": "recon",
            "name": "Разведка",
            "description": (
                "Вне боя показывает названия непосредственно соседних локаций "
                "по доступным из текущей локации выходам."
            ),
            "energy_cost": 1,
            "cooldown_turns": 3,
            "context": "out_of_combat",
            "effect": {"reveal": "adjacent_rooms"},
        },
    },
}


def available_classes() -> list[str]:
    """Return stable class IDs in presentation order."""
    return list(_PROFILES)


def create_character(class_id: str = "generalist") -> dict[str, Any]:
    """Create independent mutable JSON state; all classes begin with 6 energy."""
    if not isinstance(class_id, str) or class_id not in _PROFILES:
        raise ValueError("unknown character class")
    profile = _PROFILES[class_id]
    return {
        "class_id": class_id,
        "energy": profile["max_energy"],
        "cooldowns": {profile["ability"]["id"]: 0},
    }


def _checked_profile(state: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    """Validate persisted state so malformed inputs fail without side effects."""
    if not isinstance(state, Mapping):
        raise ValueError("character state must be a mapping")
    class_id = state.get("class_id")
    if not isinstance(class_id, str) or class_id not in _PROFILES:
        raise ValueError("unknown character class")
    profile = _PROFILES[class_id]
    ability_id = profile["ability"]["id"]
    energy = state.get("energy")
    cooldowns = state.get("cooldowns")
    if (not isinstance(energy, int) or isinstance(energy, bool)
            or not 0 <= energy <= profile["max_energy"]):
        raise ValueError("invalid character energy")
    if not isinstance(cooldowns, Mapping) or set(cooldowns) != {ability_id}:
        raise ValueError("invalid character cooldowns")
    remaining = cooldowns[ability_id]
    if (not isinstance(remaining, int) or isinstance(remaining, bool)
            or not 0 <= remaining <= profile["ability"]["cooldown_turns"]):
        raise ValueError("invalid character cooldown")
    return profile, ability_id


def describe_character(state: Mapping[str, Any]) -> dict[str, Any]:
    """Return model-facing class rules and state, without exposing world data.

    ``ready`` concerns only energy and cooldown; contextual restrictions are
    separately stated by ``context`` and the public description.  The returned
    object is a deep copy and can be safely embedded in an observation.
    """
    profile, ability_id = _checked_profile(state)
    ability = deepcopy(profile["ability"])
    ability.pop("effect")  # descriptive rule is public; evaluator applies effect
    ability["cooldown_remaining"] = state["cooldowns"][ability_id]
    ability["ready"] = (state["energy"] >= ability["energy_cost"]
                        and ability["cooldown_remaining"] == 0)
    return {
        "class_id": state["class_id"],
        "name": profile["name"],
        "energy": state["energy"],
        "max_energy": profile["max_energy"],
        "abilities": [ability],
    }


def use_ability(
    state: Mapping[str, Any],
    ability_id: str,
    *,
    in_combat: bool,
    hp: int,
    max_hp: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate one ability without mutating inputs; return new state and effect.

    Successful effects use ``damage``/``damage_type``, ``heal`` or ``reveal``.
    ``reveal='adjacent_rooms'`` requests that the game disclose only the names of
    directly adjacent rooms reachable via the current room's visible exits.
    Damage is raw: the combat subsystem applies type-dependent mitigation.  If
    ``opponent_response`` is true, the game resolves an enemy response *after*
    applying the effect, and only if the enemy is still alive.  A successful
    ability action consumes one game turn; failures leave character state intact
    but the game should still consume its turn under the ordinary invalid-action
    policy.
    """
    profile, own_ability = _checked_profile(state)
    if not isinstance(in_combat, bool):
        raise ValueError("in_combat must be boolean")
    if (not isinstance(hp, int) or isinstance(hp, bool)
            or not isinstance(max_hp, int) or isinstance(max_hp, bool)
            or max_hp <= 0 or not 0 <= hp <= max_hp):
        raise ValueError("invalid health")
    new_state = deepcopy(dict(state))
    ability = profile["ability"]

    def invalid(reason: str, message: str) -> tuple[dict[str, Any], dict[str, Any]]:
        return new_state, {"valid": False, "reason": reason, "message": message}

    if hp == 0:
        return invalid("incapacitated", "Персонаж без сознания не может действовать.")
    if ability_id != own_ability:
        return invalid("unknown_ability", "Эта способность недоступна вашему классу.")
    if state["cooldowns"][ability_id] > 0:
        return invalid("cooldown", "Способность пока восстанавливается.")
    if state["energy"] < ability["energy_cost"]:
        return invalid("insufficient_energy", "Недостаточно энергии.")
    if ability["context"] == "combat" and not in_combat:
        return invalid("requires_enemy", "Здесь нет противника для этой способности.")
    if ability["context"] == "out_of_combat" and in_combat:
        return invalid("combat_blocked", "Эту способность нельзя применять во время боя.")
    if ability["context"] == "injured" and hp >= max_hp:
        return invalid("full_health", "Здоровье уже полное.")

    new_state["energy"] -= ability["energy_cost"]
    new_state["cooldowns"][ability_id] = ability["cooldown_turns"]
    effect = deepcopy(ability["effect"])
    if "heal" in effect:
        effect["heal"] = min(effect["heal"], max_hp - hp)
    effect.update({"valid": True, "ability_id": ability_id,
                   "opponent_response": in_combat,
                   "message": f"Применена способность: {ability['name']}."})
    return new_state, effect


def advance_turn(
    state: Mapping[str, Any], *, used_ability_id: str | None = None,
) -> dict[str, Any]:
    """Tick after one game turn; the ability just used starts ticking next turn."""
    _, own_ability = _checked_profile(state)
    if used_ability_id is not None and used_ability_id != own_ability:
        raise ValueError("unknown used ability")
    new_state = deepcopy(dict(state))
    if used_ability_id != own_ability:
        new_state["cooldowns"][own_ability] = max(0, new_state["cooldowns"][own_ability] - 1)
    return new_state
