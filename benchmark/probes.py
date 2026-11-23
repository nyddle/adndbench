"""Recall probes derived only from observations and successful movements.

Answers are evaluator-only. Never send a probe dictionary as-is to an agent;
use ``public_probe`` to remove the answer. These questions test the information
that was actually shown, not details from the private generated world.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Mapping, Sequence

_QUEST = re.compile(
    r"^(?P<giver>[^:]+): найдите (?P<item>.+?) в месте «(?P<room>.+?)» "
    r"и принесите мне сюда, в «.+?»\. Я не повторю поручение\.$"
)
_REALMS_QUEST = re.compile(
    r"^(?P<giver>[^:]+): найдите (?P<item>.+?) в месте «(?P<room>.+?)» "
    r"и принесите мне сюда, в «.+?»\."
)
# Expedition briefings and NPC clues have distinct formats.  These patterns
# deliberately match only explicit observations about an item and its room;
# quest plans, inventories, and the hidden world are not used as answer keys.
_EXPEDITION_BRIEF = re.compile(
    r"\bнайдите\s+(?P<item>[^«»\n]{1,160}?)\s+в месте «(?P<room>[^»]+)»",
    re.IGNORECASE,
)
_EXPEDITION_HINT = re.compile(
    r"Поручение «(?P<title>[^»]+)», шаг \d+: найти предмет «(?P<item>[^»]+)» "
    r"в месте «(?P<room>[^»]+)»\."
)


def build_probes(trace: Sequence[Mapping[str, Any]], final_observation: Mapping[str, Any],
                 *, max_per_capability: int = 3,
                 scenario: str = "classic") -> list[dict[str, str]]:
    """Build deterministic, answerable questions from the agent's visible trace.

    ``trace`` is a sequence of {observation, action}; ``final_observation`` is
    the observation after the last action. No world internals are read. A quest
    still displayed in the last observation is excluded, so its answer is not
    accidentally supplied alongside the question. Fewer (or zero) questions are
    produced if the episode contains insufficient evidence. For ``realms`` and
    ``expedition``,
    compass displacements are only combined within the same observed zone;
    stairs are still eligible for navigation recall.
    """
    if scenario not in ("classic", "realms", "expedition"):
        raise ValueError("unknown scenario")
    if not isinstance(max_per_capability, int) or isinstance(max_per_capability, bool) or max_per_capability < 0:
        raise ValueError("max_per_capability must be a non-negative integer")
    probes: list[dict[str, str]] = []
    seen_quests: set[tuple[str, str]] = set()
    seen_edges: set[tuple[str, str]] = set()
    memory_count = navigation_count = reasoning_count = 0
    seen_pairs: set[tuple[str, str]] = set()
    # Successful observed movement only; never use private world coordinates.
    path: list[tuple[str, str, str]] = []
    vectors = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}
    final_text = json.dumps(final_observation, ensure_ascii=False, sort_keys=True).casefold()
    for index, turn in enumerate(trace):
        obs = turn.get("observation", {})
        if not isinstance(obs, Mapping):
            continue
        if path and obs.get("room") != path[-1][1]:
            path.clear()
        message = obs.get("message")
        if isinstance(message, str) and message != final_observation.get("message"):
            match = (_QUEST.fullmatch(message) if scenario == "classic"
                     else _REALMS_QUEST.match(message) if scenario == "realms"
                     else None)
            if match:
                giver, item, location = match.group("giver", "item", "room")
                quest_key = (giver, item)
                if (quest_key not in seen_quests and memory_count < max_per_capability
                        and location.casefold() not in final_text):
                    seen_quests.add(quest_key)
                    memory_count += 1
                    probes.append({
                        "id": f"quest_memory_{memory_count}",
                        "capability": "quest_memory",
                        "question": f"В каком месте {giver} попросил найти {item}? Ответьте только названием места.",
                        "answer": location,
                    })
            if scenario == "expedition":
                # Hints may be provided by a third-party informant, so avoid
                # claiming that the current NPC originally gave the quest.
                hints = list(_EXPEDITION_HINT.finditer(message))
                briefings = list(_EXPEDITION_BRIEF.finditer(message))
                for clue in hints + briefings:
                    item, location = clue.group("item", "room")
                    title = clue.groupdict().get("title")
                    if title:
                        question = (f"В каком месте нужно найти {item} по поручению «{title}»? "
                                    "Ответьте только названием места.")
                    else:
                        question = f"В каком месте поручили найти {item}? Ответьте только названием места."
                    quest_key = (item.casefold(), location.casefold())
                    if (quest_key in seen_quests or memory_count >= max_per_capability
                            or location.casefold() in final_text
                            or location.casefold() in question.casefold()):
                        continue
                    seen_quests.add(quest_key)
                    memory_count += 1
                    probes.append({
                        "id": f"quest_memory_{memory_count}",
                        "capability": "quest_memory",
                        "question": question,
                        "answer": location,
                    })
        action = turn.get("action")
        if not isinstance(action, Mapping) or action.get("type") != "move":
            continue
        following = (trace[index + 1].get("observation", {})
                     if index + 1 < len(trace) else final_observation)
        if not isinstance(following, Mapping):
            continue
        origin, direction, destination = obs.get("room"), action.get("direction"), following.get("room")
        if not all(isinstance(v, str) and v for v in (origin, direction, destination)):
            continue
        if origin == destination:
            continue
        if direction not in obs.get("exits", []):
            path.clear()
            continue
        # In realms, each zone has its own horizontal coordinate system.
        # Stairs connect zones and must not be interpreted as horizontal
        # displacement, even if subsequent room names happen to match.
        horizontal = direction in vectors
        same_zone = (scenario == "classic" or
                     (isinstance(obs.get("zone"), str) and obs.get("zone")
                      and obs.get("zone") == following.get("zone")))
        if not horizontal or not same_zone:
            path.clear()
        else:
            path.append((origin, destination, direction))
        # Every candidate spans at least two successful moves. Sum the visible
        # directions, which handles turns and cancellation without hidden data.
        dx = dy = 0
        for length, (start, _, step_direction) in enumerate(reversed(path), 1):
            vx, vy = vectors[step_direction]
            dx += vx
            dy += vy
            pair = (start, destination)
            if length < 2 or reasoning_count >= max_per_capability or pair in seen_pairs:
                continue
            if (dx == 0) == (dy == 0) or start == destination:
                continue
            answer = ("east" if dx > 0 else "west") if dx else ("south" if dy > 0 else "north")
            seen_pairs.add(pair)
            reasoning_count += 1
            probes.append({
                "id": f"spatial_reasoning_{reasoning_count}",
                "capability": "spatial_reasoning",
                "question": (f"В каком направлении расположена комната «{destination}» "
                             f"относительно комнаты «{start}»? Ответьте одним направлением на английском."),
                "answer": answer,
            })
        edge = (origin, direction)
        if (edge in seen_edges or navigation_count >= max_per_capability
                or destination.casefold() in final_text):
            continue
        seen_edges.add(edge)
        navigation_count += 1
        probes.append({
            "id": f"navigation_recall_{navigation_count}",
            "capability": "navigation_recall",
            "question": (f"В какую комнату вы попадали, выйдя из «{origin}» в направлении "
                         f"{direction}? Ответьте только названием комнаты."),
            "answer": destination,
        })
    return probes


def public_probe(probe: Mapping[str, str]) -> dict[str, str]:
    """Return the only fields permitted in the model-facing question."""
    return {"id": probe["id"], "question": probe["question"]}


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    value = value.strip(' \t\r\n"\'«»„“”.,!?;:')
    return " ".join(value.split())


def check_answer(probe: Mapping[str, str], answer: Any) -> bool:
    """Check an exact answer, allowing harmless case, whitespace and quoting."""
    return isinstance(answer, str) and _normalize(answer) == _normalize(probe["answer"])
