"""Deterministic quest plans and a small event-driven progress reducer.

Plans are evaluator data. The caller owns world, player inventory and action
validation; only *confirmed* events should be sent to :func:`advance`.
No model, environment, global RNG or mutable game state is accessed here.
"""
from __future__ import annotations

from copy import deepcopy
from collections import deque
import hashlib
from typing import Any, Mapping

QUEST_VERSION = "quests-0.1.0"
DIFFICULTIES = ("easy", "medium", "hard")


class _Stream:
    def __init__(self, seed: str, difficulty: str):
        self.key = f"{QUEST_VERSION}\0{seed}\0{difficulty}".encode("utf-8")
        self.counter = 0

    def below(self, count: int) -> int:
        if count <= 0:
            raise ValueError("cannot choose from an empty list")
        limit = (1 << 256) - ((1 << 256) % count)
        while True:
            raw = self.key + b"\0" + str(self.counter).encode("ascii")
            self.counter += 1
            number = int.from_bytes(hashlib.sha256(raw).digest(), "big")
            if number < limit:
                return number % count

    def shuffle(self, values: list[Any]) -> None:
        for index in range(len(values) - 1, 0, -1):
            selected = self.below(index + 1)
            values[index], values[selected] = values[selected], values[index]


def _map_parts(world: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], Mapping[str, str]]:
    """Validate the map fields this module consumes and return stable indexes."""
    if not isinstance(world, Mapping) or not isinstance(world.get("rooms"), list):
        raise ValueError("world.rooms must be a list")
    sites = world.get("sites")
    if not isinstance(sites, Mapping):
        raise ValueError("world.sites must be a mapping")
    rooms: dict[str, Mapping[str, Any]] = {}
    for room in world["rooms"]:
        if not isinstance(room, Mapping):
            raise ValueError("invalid room")
        rid, name, zone = room.get("id"), room.get("name"), room.get("zone")
        if not all(isinstance(v, str) and v for v in (rid, name, zone)) or rid in rooms:
            raise ValueError("room IDs, names and zones must be non-empty; IDs must be unique")
        rooms[rid] = room
    for site in ("elder", "herbalist", "wizard", "dragon", "herb"):
        if not isinstance(sites.get(site), str) or sites[site] not in rooms:
            raise ValueError(f"missing or invalid site: {site}")
    if any(not isinstance(rid, str) or rid not in rooms for rid in sites.values()):
        raise ValueError("all sites must refer to valid rooms")
    if len({room["name"] for room in rooms.values()}) != len(rooms):
        raise ValueError("room names must be unique")
    reverse = {"north": "south", "south": "north", "east": "west",
               "west": "east", "up": "down", "down": "up"}
    for rid, room in rooms.items():
        exits = room.get("exits")
        if not isinstance(exits, Mapping):
            raise ValueError("room exits must be a mapping")
        for direction, target in exits.items():
            if direction not in reverse or not isinstance(target, str) or target not in rooms:
                raise ValueError("invalid room exit")
            if not isinstance(rooms[target].get("exits"), Mapping) or rooms[target]["exits"].get(reverse[direction]) != rid:
                raise ValueError("room exits must be reciprocal")
    reachable = {sites["elder"]}
    queue = deque([sites["elder"]])
    while queue:
        for target in rooms[queue.popleft()]["exits"].values():
            if target not in reachable:
                reachable.add(target)
                queue.append(target)
    if len(reachable) != len(rooms):
        raise ValueError("world must be connected")
    return rooms, sites


def _objective(oid: str, event: str, target_id: str, room_id: str,
               requires: list[str], description: str, *, sticky: bool = False) -> dict[str, Any]:
    return {"id": oid, "event": event, "target_id": target_id, "room_id": room_id,
            "requires": list(requires), "sticky": sticky, "description": description}


def generate_quests(seed: str | int, world: Mapping[str, Any], difficulty: str = "easy") -> dict[str, Any]:
    """Generate an immutable-by-convention JSON-compatible quest plan.

    ``world`` uses the maps axis contract: rooms with string IDs/names/zones and
    a sites mapping. Difficulty controls the quest graph, not map generation.
    On hard the elder openly requires the scout's errand before the wizard can
    provide the ward. NPCs, target rooms, prerequisites and rewards are explicit
    in the respective quest briefing; no hidden precondition is invented.
    """
    if not isinstance(seed, (str, int)) or isinstance(seed, bool):
        raise ValueError("seed must be a string or integer")
    if difficulty not in DIFFICULTIES:
        raise ValueError("difficulty must be easy, medium or hard")
    rooms, sites = _map_parts(world)
    stream = _Stream(str(seed), difficulty)
    reserved = {value for value in sites.values() if isinstance(value, str)}

    def pick(zone: str) -> str:
        candidates = sorted(rid for rid, room in rooms.items() if room["zone"] == zone and rid not in reserved)
        if not candidates:
            raise ValueError(f"insufficient distinct free locations in zone {zone}")
        stream.shuffle(candidates)
        selected = candidates[0]
        reserved.add(selected)
        return selected

    npcs = [
        {"id": "elder", "name": "Старейшина", "room_id": sites["elder"]},
        {"id": "herbalist", "name": "Травница", "room_id": sites["herbalist"]},
        {"id": "wizard", "name": "Маг", "room_id": sites["wizard"]},
    ]
    items = [{"id": "star_heart", "name": "сердце звезды"},
             {"id": "herb", "name": "серебряная трава"},
             {"id": "ward", "name": "рунический оберег"}]
    if difficulty in ("medium", "hard"):
        scout_room = pick("overworld")
        parcel_room = pick("mountain")
        npcs.append({"id": "scout", "name": "Следопыт", "room_id": scout_room})
        items.extend([{"id": "sealed_parcel", "name": "запечатанный свёрток"},
                      {"id": "scout_seal", "name": "печать следопыта"}])
    if difficulty == "hard":
        archivist_room = pick("overworld")
        book_room = pick("tower")
        npcs.append({"id": "archivist", "name": "Архивариус", "room_id": archivist_room})
        items.append({"id": "old_tome", "name": "старая летопись"})

    def name(rid: str) -> str:
        return str(rooms[rid]["name"])

    wizard_prereqs = ["main_accept"]
    if difficulty == "hard":
        wizard_prereqs.append("scout_deliver")
    main_brief = (f"Найдите сердце звезды в месте «{name(sites['dragon'])}» и принесите его "
                  f"в место «{name(sites['elder'])}». Дракона можно победить до посещения мага; "
                  f"снять печать с реликвии поможет оберег мага в месте «{name(sites['wizard'])}».")
    if difficulty == "hard":
        main_brief += (f" Сначала помогите Следопыту в месте «{name(scout_room)}»: принесите "
                       f"ему запечатанный свёрток из места «{name(parcel_room)}». "
                       "Его печать нужна, чтобы маг выдал оберег; награда — одно зелье и печать.")
    main_objectives = [
        _objective("main_accept", "talk", "elder", sites["elder"], [], "Получить поручение старейшины."),
        _objective("main_ward", "talk", "wizard", sites["wizard"], wizard_prereqs,
                   "Получить у мага оберег для снятия печати.", sticky=(difficulty != "hard")),
        _objective("main_dragon", "defeat", "dragon", sites["dragon"], ["main_accept"],
                   "Победить дракона в подземелье.", sticky=True),
        _objective("main_relic", "search", "star_heart", sites["dragon"],
                   ["main_ward", "main_dragon"], "Снять печать и найти сердце звезды."),
        _objective("main_deliver", "talk", "elder", sites["elder"], ["main_relic"],
                   "Вернуть сердце звезды старейшине."),
    ]
    quests = [{"id": "main", "giver_id": "elder", "title": "Сердце звезды", "required": True,
               "briefing": main_brief, "objectives": main_objectives, "completion_objective": "main_deliver",
               "rewards": {"potions": 0, "items": []}}]
    herb_brief = (f"Найдите серебряную траву в месте «{name(sites['herb'])}» и принесите её "
                  f"травнице в место «{name(sites['herbalist'])}». Награда — два зелья.")
    quests.append({"id": "herb", "giver_id": "herbalist", "title": "Серебряная трава", "required": False,
                   "briefing": herb_brief, "completion_objective": "herb_deliver",
                   "rewards": {"potions": 2, "items": []}, "objectives": [
        _objective("herb_accept", "talk", "herbalist", sites["herbalist"], [], "Взять поручение травницы."),
        _objective("herb_collect", "search", "herb", sites["herb"], ["herb_accept"], "Найти серебряную траву."),
        _objective("herb_deliver", "talk", "herbalist", sites["herbalist"], ["herb_collect"], "Вернуть траву травнице."),
    ]})
    if difficulty in ("medium", "hard"):
        scout_brief = (f"Найдите запечатанный свёрток в месте «{name(parcel_room)}» и принесите "
                       f"его Следопыту в место «{name(scout_room)}». Награда — одно зелье и печать следопыта.")
        quests.append({"id": "scout", "giver_id": "scout", "title": "Свёрток следопыта",
                       "required": difficulty == "hard", "briefing": scout_brief,
                       "completion_objective": "scout_deliver",
                       "rewards": {"potions": 1, "items": ["scout_seal"]}, "objectives": [
            _objective("scout_accept", "talk", "scout", scout_room, [], "Взять поручение следопыта."),
            _objective("scout_collect", "search", "sealed_parcel", parcel_room, ["scout_accept"], "Найти свёрток."),
            _objective("scout_deliver", "talk", "scout", scout_room, ["scout_collect"], "Вернуть свёрток следопыту."),
        ]})
    if difficulty == "hard":
        archive_brief = (f"После помощи Следопыту найдите старую летопись в месте «{name(book_room)}» "
                         f"и принесите её архивариусу в место «{name(archivist_room)}». Награда — одно зелье.")
        quests.append({"id": "archive", "giver_id": "archivist", "title": "Старая летопись", "required": False,
                       "briefing": archive_brief, "completion_objective": "archive_deliver",
                       "rewards": {"potions": 1, "items": []}, "objectives": [
            _objective("archive_accept", "talk", "archivist", archivist_room, ["scout_deliver"],
                       "После помощи следопыту взять поручение архивариуса."),
            _objective("archive_collect", "search", "old_tome", book_room, ["archive_accept"], "Найти летопись."),
            _objective("archive_deliver", "talk", "archivist", archivist_room, ["archive_collect"], "Вернуть летопись."),
        ]})
    plan = {"version": QUEST_VERSION, "difficulty": difficulty, "npcs": npcs, "items": items, "quests": quests}
    validate_plan(plan, world)
    return plan


def validate_plan(plan: Mapping[str, Any], world: Mapping[str, Any]) -> None:
    """Reject unknown references and cycles, including cross-quest dependencies."""
    rooms, sites = _map_parts(world)
    if not isinstance(plan, Mapping):
        raise ValueError("quest plan must be a mapping")
    npcs, items, quests = plan.get("npcs"), plan.get("items"), plan.get("quests")
    if not all(isinstance(value, list) for value in (npcs, items, quests)):
        raise ValueError("npcs, items and quests must be lists")

    def by_id(entries: list[Any], label: str) -> dict[str, Mapping[str, Any]]:
        result: dict[str, Mapping[str, Any]] = {}
        for entry in entries:
            if not isinstance(entry, Mapping) or not isinstance(entry.get("id"), str) or not entry["id"] or entry["id"] in result:
                raise ValueError(f"invalid or duplicate {label} ID")
            result[entry["id"]] = entry
        return result

    npc_by_id, item_by_id, quest_by_id = by_id(npcs, "npc"), by_id(items, "item"), by_id(quests, "quest")
    if not quest_by_id:
        raise ValueError("quest plan is empty")
    for npc in npc_by_id.values():
        if npc.get("room_id") not in rooms or not isinstance(npc.get("name"), str) or not npc["name"]:
            raise ValueError("NPC has an invalid location or name")
    for item in item_by_id.values():
        if not isinstance(item.get("name"), str) or not item["name"]:
            raise ValueError("item has an invalid name")
    objectives: dict[str, Mapping[str, Any]] = {}
    for quest in quest_by_id.values():
        if quest.get("giver_id") not in npc_by_id or not isinstance(quest.get("objectives"), list) or not quest["objectives"]:
            raise ValueError("quest must have a valid giver and objectives")
        if not isinstance(quest.get("required"), bool) or not isinstance(quest.get("briefing"), str) or not quest["briefing"]:
            raise ValueError("quest must declare whether it is required and contain a briefing")
        own = by_id(quest["objectives"], "objective")
        if set(objectives) & set(own):
            raise ValueError("duplicate objective ID across quests")
        if quest.get("completion_objective") not in own:
            raise ValueError("completion objective must belong to its quest")
        objectives.update(own)
        reward = quest.get("rewards")
        if (not isinstance(reward, Mapping) or type(reward.get("potions")) is not int or reward["potions"] < 0
                or not isinstance(reward.get("items"), list) or any(x not in item_by_id for x in reward["items"])):
            raise ValueError("invalid rewards")
    for obj in objectives.values():
        event, target, room_id, prereqs = obj.get("event"), obj.get("target_id"), obj.get("room_id"), obj.get("requires")
        if event not in ("talk", "search", "defeat") or room_id not in rooms or not isinstance(target, str):
            raise ValueError("invalid event, target or room")
        if event == "talk" and (target not in npc_by_id or npc_by_id[target]["room_id"] != room_id):
            raise ValueError("talk objective must point to an NPC at that location")
        if event == "search" and target not in item_by_id:
            raise ValueError("search objective must point to a known item")
        if event == "defeat" and (target != "dragon" or sites.get("dragon") != room_id):
            raise ValueError("defeat objective must point to the dragon location")
        if not isinstance(prereqs, list) or any(not isinstance(x, str) or x not in objectives for x in prereqs):
            raise ValueError("unknown objective prerequisite")
        if not isinstance(obj.get("sticky"), bool) or not isinstance(obj.get("description"), str) or not obj["description"]:
            raise ValueError("objective must declare stickiness and visible description")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(oid: str) -> None:
        if oid in visiting:
            raise ValueError("cyclic quest dependency")
        if oid in visited:
            return
        visiting.add(oid)
        for prerequisite in objectives[oid]["requires"]:
            visit(prerequisite)
        visiting.remove(oid)
        visited.add(oid)

    for oid in objectives:
        visit(oid)


def initial_state() -> dict[str, list[str]]:
    """Return new per-game state; only the caller may associate it with a game."""
    return {"completed_objectives": [], "remembered_events": [], "completed_quests": []}


def eligible_objectives(plan: Mapping[str, Any], state: Mapping[str, Any], event: Mapping[str, Any]) -> list[str]:
    """List currently actionable objectives matching an event before applying it.

    An engine can use this to decide whether a search may grant an item, or a
    conversation may award the wizard's ward. It does not itself validate a
    player's action or mutate state. An early dragon defeat may still be sent
    to ``advance`` for its sticky fact even if no objective is eligible yet.
    """
    if (not isinstance(event, Mapping) or event.get("event") not in ("talk", "search", "defeat")
            or not isinstance(event.get("target_id"), str) or not isinstance(event.get("room_id"), str)):
        raise ValueError("invalid event")
    if not isinstance(state, Mapping) or not isinstance(state.get("completed_objectives"), list):
        raise ValueError("invalid quest state")
    done = set(state["completed_objectives"])
    return [obj["id"] for quest in plan["quests"] for obj in quest["objectives"]
            if obj["id"] not in done and set(obj["requires"]) <= done
            and all(event.get(key) == obj[key] for key in ("event", "target_id", "room_id"))]


def required_complete(plan: Mapping[str, Any], state: Mapping[str, Any]) -> bool:
    """Whether every explicitly required quest is complete."""
    if not isinstance(state, Mapping) or not isinstance(state.get("completed_quests"), list):
        raise ValueError("invalid quest state")
    required = {quest["id"] for quest in plan["quests"] if quest["required"]}
    return bool(required) and required <= set(state["completed_quests"])


def advance(plan: Mapping[str, Any], state: Mapping[str, Any], event: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Advance from one *confirmed* event, returning new state and rewards.

    Event schema is ``{'event': 'talk'|'search'|'defeat', 'target_id': str,
    'room_id': str}``. Only exact matching objectives can advance. Sticky facts
    preserve dragon defeat (and early unrestricted wizard visits) until their
    prerequisites are met. The game engine must only emit a search event when
    it has actually granted the item, and must apply quest rewards once per
    returned ``quest_completed`` notification. The input state is not mutated.
    """
    if (not isinstance(event, Mapping) or event.get("event") not in ("talk", "search", "defeat")
            or not isinstance(event.get("target_id"), str) or not isinstance(event.get("room_id"), str)):
        raise ValueError("invalid confirmed event")
    if not isinstance(state, Mapping) or any(not isinstance(state.get(key), list) for key in
            ("completed_objectives", "remembered_events", "completed_quests")):
        raise ValueError("invalid quest state")
    objectives = [obj for quest in plan["quests"] for obj in quest["objectives"]]
    objective_ids = {obj["id"] for obj in objectives}
    quest_ids = {quest["id"] for quest in plan["quests"]}
    done, remembered, completed = (set(state[key]) for key in
                                   ("completed_objectives", "remembered_events", "completed_quests"))
    if not done <= objective_ids or not remembered <= objective_ids or not completed <= quest_ids:
        raise ValueError("quest state contains unknown IDs")
    matches = {obj["id"] for obj in objectives if all(event.get(key) == obj[key]
               for key in ("event", "target_id", "room_id"))}
    remembered.update(obj["id"] for obj in objectives if obj["id"] in matches and obj["sticky"])
    previous = set(done)
    # Re-evaluate sticky facts after unlocking prerequisites; normal events can
    # only apply to objectives whose prerequisites were already true before
    # this event, avoiding two stages being fulfilled by the same interaction.
    changed = True
    while changed:
        changed = False
        for obj in objectives:
            oid = obj["id"]
            prerequisites = set(obj["requires"])
            usable = (oid in remembered and obj["sticky"]) or (oid in matches and prerequisites <= previous)
            if oid not in done and prerequisites <= done and usable:
                done.add(oid)
                changed = True
    notifications = []
    for quest in plan["quests"]:
        if quest["id"] not in completed and quest["completion_objective"] in done:
            completed.add(quest["id"])
            notifications.append({"type": "quest_completed", "quest_id": quest["id"],
                                  "rewards": deepcopy(quest["rewards"])})
    return {"completed_objectives": sorted(done), "remembered_events": sorted(remembered),
            "completed_quests": sorted(completed)}, notifications
