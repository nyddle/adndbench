"""Auditable episode outcomes, without inferring cognitive abilities.

Coverage and quest completion can support broader evaluation, but are not
measurements of spatial reasoning or memory by themselves. Such measurements
require dedicated, independently scored tasks, which this module does not infer.
"""

from __future__ import annotations

from typing import Any, Mapping


def _fraction(numerator: Any, denominator: Any) -> float | None:
    """Return a fraction only when both counts are available and meaningful."""
    if (
        not isinstance(numerator, int)
        or isinstance(numerator, bool)
        or not isinstance(denominator, int)
        or isinstance(denominator, bool)
        or denominator <= 0
        or numerator < 0
        or numerator > denominator
    ):
        return None
    return numerator / denominator


def score(result: Mapping[str, Any]) -> dict[str, Any]:
    """Summarize a Game.result() as JSON-serializable, inspectable outcomes.

    Rates with missing or zero denominators are null instead of misleadingly
    reporting success or failure. The individual counts remain available so
    that users can compute aggregate rates across multiple seeds correctly.
    """
    turns = result.get("turns")
    invalid = result.get("invalid_actions")
    valid = (
        turns - invalid
        if isinstance(turns, int)
        and not isinstance(turns, bool)
        and isinstance(invalid, int)
        and not isinstance(invalid, bool)
        and 0 <= invalid <= turns
        else None
    )
    completed = result.get("quests_completed")
    total_quests = result.get("quests_total")
    visited = result.get("rooms_visited")
    total_rooms = result.get("rooms_total")
    deaths = result.get("deaths")
    categories = (
        "navigation_recall", "spatial_reasoning", "quest_memory", "tactics", "strategy"
    )
    supplied_probes = result.get("probe_results")
    if not isinstance(supplied_probes, Mapping):
        supplied_probes = {}
    capability_scores = {}
    probe_counts = {}
    for category in categories:
        counts = supplied_probes.get(category)
        if isinstance(counts, Mapping):
            correct = counts.get("correct")
            total = counts.get("total")
            rate = _fraction(correct, total)
        else:
            correct = total = rate = None
        # Reject inconsistent or empty counts instead of fabricating a score.
        capability_scores[category] = rate
        probe_counts[category] = (
            {"correct": correct, "total": total} if rate is not None else None
        )
    return {
        "seed": result.get("seed"),
        "terminal_reason": result.get("terminal_reason"),
        "outcomes": {
            "quests": {
                "completed": completed,
                "total": total_quests,
                "completion_rate": _fraction(completed, total_quests),
            },
            "exploration": {
                "rooms_visited": visited,
                "rooms_total": total_rooms,
                "coverage": _fraction(visited, total_rooms),
                "moves": result.get("moves"),
            },
            "actions": {
                "turns": turns,
                "invalid": invalid,
                "valid_rate": _fraction(valid, turns),
            },
            "combat_and_resources": {
                "attacks": result.get("attacks"),
                "damage_taken": result.get("damage_taken"),
                "potions_used": result.get("potions_used"),
                "deaths": deaths,
            },
        },
        "capability_scores": capability_scores,
        "probe_counts": probe_counts,
        "note": (
            "Outcome metrics are not direct tests of cognitive abilities. "
            "Capability scores reflect dedicated probes when present, not "
            "general abilities; null means no valid probes were provided."
        ),
    }
