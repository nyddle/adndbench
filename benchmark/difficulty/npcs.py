"""Deterministic, source-backed NPC dialogue for the configurable adventure.

The index produced here contains privileged quest and map knowledge.  It is
owned by the game engine: agents get only the topics for the NPC in the current
room and the response to the single topic they ask about, never the index.
"""
from __future__ import annotations

import hashlib
from typing import Any, Mapping

VERSION = "npc-0.1.0"
DIFFICULTIES = ("easy", "medium", "hard")


def _named_index(rows: Any, label: str) -> dict[str, Mapping[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError(f"{label} must be a list")
    found: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError(f"{label} entries must be mappings")
        key, name = row.get("id"), row.get("name")
        if not isinstance(key, str) or not key or not isinstance(name, str) or not name or key in found:
            raise ValueError(f"{label} entries require unique string ids and names")
        found[key] = row
    return found


def _choice(seed: str, difficulty: str, fact_id: str, candidates: list[str]) -> str:
    # Independent per-fact hashing means adding unrelated facts doesn't change
    # who knows existing ones. Never depend on Python's randomized hash().
    payload = f"{VERSION}\0{seed}\0{difficulty}\0{fact_id}".encode("utf-8")
    number = int.from_bytes(hashlib.sha256(payload).digest(), "big")
    return candidates[number % len(candidates)]


def build_npc_knowledge(seed: str | int, world: Mapping[str, Any],
                        plan: Mapping[str, Any], difficulty: str = "easy") -> dict[str, Any]:
    """Build evaluator-only knowledge from the actual map and quest plan.

    ``world`` has ``rooms`` (id/name) and ``sites`` (semantic id -> room id).
    ``plan`` has ``npcs``, ``items`` and ``quests``. Each quest has id, title,
    giver_id, objectives; each objective has id, event, target_id, room_id,
    requires. Objective topics are all discoverable: the giver holds every fact
    on easy, but on medium/hard some facts are held by other NPCs. All topics
    have a human-readable label that omits undiscovered room names. On each NPC,
    the ``sources`` topic lists other NPC names, without their locations.

    Map names and each objective's true location are resolved here, never
    invented. The returned JSON-like object is private and must not be put
    directly in the model's observation.
    """
    if isinstance(seed, bool) or not isinstance(seed, (str, int)):
        raise ValueError("seed must be a string or integer")
    if difficulty not in DIFFICULTIES:
        raise ValueError("difficulty must be easy, medium or hard")
    if not isinstance(world, Mapping) or not isinstance(plan, Mapping):
        raise ValueError("world and quest plan must be mappings")
    rooms = _named_index(world.get("rooms"), "rooms")
    npcs = _named_index(plan.get("npcs"), "npcs")
    items = _named_index(plan.get("items"), "items")
    if not npcs:
        raise ValueError("at least one NPC is required")
    for npc in npcs.values():
        if npc.get("room_id") not in rooms:
            raise ValueError("NPC references an unknown room")
    sites = world.get("sites", {})
    if not isinstance(sites, Mapping):
        raise ValueError("world sites must be a mapping")
    quests = plan.get("quests")
    if not isinstance(quests, list):
        raise ValueError("quests must be a list")

    npc_ids = sorted(npcs)
    topics: dict[str, dict[str, Any]] = {npc_id: {} for npc_id in npc_ids}
    npc_names = ", ".join(str(npcs[npc_id]["name"]) for npc_id in npc_ids)
    for npc_id in npc_ids:
        topics[npc_id]["sources"] = {
            "id": "sources", "label": "Кто ещё знает о мире и поручениях?",
            "message": f"Спросите следующих жителей: {npc_names}.",
        }

    ids_seen: set[str] = set()
    all_objectives: dict[str, tuple[str, int]] = {}
    # Dependencies can cross quest boundaries: first build a global index,
    # then render a prerequisite's quest title and step without inventing it.
    for quest in quests:
        if not isinstance(quest, Mapping):
            raise ValueError("quest entries must be mappings")
        qid, title, giver = quest.get("id"), quest.get("title"), quest.get("giver_id")
        objectives = quest.get("objectives")
        if (not isinstance(qid, str) or not qid or qid in ids_seen
                or not isinstance(title, str) or not title or giver not in npcs
                or not isinstance(objectives, list) or not objectives):
            raise ValueError("invalid quest id, title, giver or objectives")
        ids_seen.add(qid)
        objective_ids = [obj.get("id") if isinstance(obj, Mapping) else None for obj in objectives]
        if any(not isinstance(i, str) or not i for i in objective_ids) or len(set(objective_ids)) != len(objective_ids):
            raise ValueError("objectives need unique ids")
        for step, oid in enumerate(objective_ids):
            if oid in all_objectives:
                raise ValueError("objective ids must be globally unique")
            all_objectives[oid] = (title, step + 1)

    for quest in quests:
        qid, title, giver = quest["id"], quest["title"], quest["giver_id"]
        objectives = quest["objectives"]
        for step, obj in enumerate(objectives):
            oid, event, target, room_id, requires = (obj.get(k) for k in ("id", "event", "target_id", "room_id", "requires"))
            if room_id not in rooms or not isinstance(target, str) or not target:
                raise ValueError("objective references an unknown room or target")
            if not isinstance(requires, list) or any(not isinstance(i, str) or i not in all_objectives for i in requires):
                raise ValueError("objective has unknown prerequisites")
            room_name = rooms[room_id]["name"]
            if event == "talk":
                if target not in npcs or npcs[target].get("room_id") != room_id:
                    raise ValueError("talk objective must reference the NPC's actual room")
                action = f"поговорить с персонажем «{npcs[target]['name']}»"
            elif event == "search":
                if target not in items:
                    raise ValueError("search objective references an unknown item")
                action = f"найти предмет «{items[target]['name']}»"
            elif event == "defeat":
                if target not in sites or sites[target] != room_id:
                    raise ValueError("defeat objective must reference the enemy's actual site")
                target_name = "дракон" if target == "dragon" else target
                action = f"победить противника «{target_name}»"
            else:
                raise ValueError("unsupported objective event")
            # The target is in the response only. Labels and topic IDs never
            # contain hidden room names or private coordinates.
            fact_id = f"quest:{qid}:{oid}"
            prerequisites = ""
            if requires:
                stages = ", ".join(f"«{all_objectives[i][0]}», шаг {all_objectives[i][1]}" for i in requires)
                prerequisites = f" Сначала выполните: {stages}."
            message = f"Поручение «{title}», шаг {step + 1}: {action} в месте «{room_name}».{prerequisites}"
            other_ids = [i for i in npc_ids if i != giver]
            if difficulty == "easy" or not other_ids or (difficulty == "medium" and step == 0):
                holder = giver
            else:
                holder = _choice(str(seed), difficulty, fact_id, other_ids)
            topics[holder][fact_id] = {
                "id": fact_id, "label": f"Поручение «{title}»: шаг {step + 1}", "message": message,
            }

    return {"version": VERSION, "difficulty": difficulty,
            "npcs": {npc_id: {"name": npcs[npc_id]["name"], "topics": topics[npc_id]} for npc_id in npc_ids}}


def get_topics(knowledge: Mapping[str, Any], npc_id: str) -> list[dict[str, str]]:
    """Return only public, answer-free topic identifiers and labels for one NPC."""
    if not isinstance(npc_id, str):
        return []
    npcs = knowledge.get("npcs", {}) if isinstance(knowledge, Mapping) else {}
    npc = npcs.get(npc_id, {}) if isinstance(npcs, Mapping) else {}
    topics = npc.get("topics", {}) if isinstance(npc, Mapping) else {}
    if not isinstance(topics, Mapping):
        return []
    return [{"id": value["id"], "label": value["label"]} for _, value in sorted(topics.items())]


def dialogue(knowledge: Mapping[str, Any], npc_id: str, topic_id: str) -> dict[str, Any]:
    """Answer one available topic; unknown NPCs and topics reveal no facts."""
    if not isinstance(npc_id, str):
        return {"valid": False, "message": "Собеседник не знает такой темы."}
    npcs = knowledge.get("npcs", {}) if isinstance(knowledge, Mapping) else {}
    npc = npcs.get(npc_id, {}) if isinstance(npcs, Mapping) else {}
    topics = npc.get("topics", {}) if isinstance(npc, Mapping) else {}
    fact = topics.get(topic_id) if isinstance(topics, Mapping) and isinstance(topic_id, str) else None
    if not isinstance(fact, Mapping):
        return {"valid": False, "message": "Собеседник не знает такой темы."}
    return {"valid": True, "message": fact["message"]}
