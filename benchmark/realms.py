"""A seeded, partially observed multi-region adventure.

All world internals and event records are evaluator-only.  The model receives
only ``observe()`` and information it has previously observed.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

ENGINE_VERSION = "realms-0.1.0"
DEFAULT_MAX_TURNS = 300
DIRECTIONS = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}
OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east", "up": "down", "down": "up"}
ALL_DIRECTIONS = (*DIRECTIONS, "up", "down")

SYSTEM_PROMPT = """You are playing a turn-based fantasy adventure. Complete the main quest and survive.
Explore the open lands, mountain, wizard's tower and dragon dungeon. You see only the current
location; remember the map and NPC instructions. Each turn answer with exactly one JSON object
and no other text. Actions: {"type":"move","direction":"north|south|east|west|up|down"},
{"type":"talk"}, {"type":"search"}, {"type":"attack"}, {"type":"defend"},
{"type":"potion"}, {"type":"rest"}. Move only through listed exits. Up/down link regions;
compass directions are consistent within each region. Talk to the elder at the refuge to
accept the main quest, then find the wizard in the tower. The wizard's rune reduces dragon
breath damage by 2 and is required to open the relic's seal. Defeat the dragon, search its lair
after accepting the quest and obtaining the rune, then return the relic to the elder. The herbalist's quest is optional.
The enemy's announced intent is its response to your next combat action. Attack deals 3 damage;
defend reduces the response to 1 HP and makes the next attack deal 5. A living ordinary enemy
deals 2; the dragon alternates fire breath for 6 and claws for 2. Killing an enemy prevents its
response. Potion heals up to 6 HP but the enemy responds; retreat costs 3 HP while an enemy is
alive. Rest at the initial refuge consumes one ration and restores up to 8 HP. Invalid actions
consume a turn. Quest details are given only once. Your current observation is supplied as JSON."""


class _Random:
    """Versioned SHA-256 counter generator, independent of Python's hash seed."""
    def __init__(self, seed: str):
        self.seed = seed
        self.counter = 0

    def below(self, n: int) -> int:
        if n <= 0:
            raise ValueError("empty range")
        limit = (1 << 256) - (1 << 256) % n
        while True:
            raw = f"adventure:{ENGINE_VERSION}:{self.seed}:{self.counter}".encode("utf8")
            self.counter += 1
            value = int.from_bytes(hashlib.sha256(raw).digest(), "big")
            if value < limit:
                return value % n

    def shuffle(self, values: list[Any]) -> None:
        for i in range(len(values) - 1, 0, -1):
            j = self.below(i + 1)
            values[i], values[j] = values[j], values[i]


@dataclass
class Room:
    name: str
    zone: str
    exits: dict[str, int] = field(default_factory=dict)
    npc: str | None = None
    enemy: str | None = None
    enemy_hp: int = 0
    enemy_phase: int = 0


@dataclass
class Quest:
    key: str
    giver: str
    giver_room: int
    item: str
    item_room: int
    required: bool
    accepted: bool = False
    collected: bool = False
    completed: bool = False


@dataclass
class World:
    rooms: list[Room]
    quests: list[Quest]
    wizard_room: int
    dragon_room: int


def _names(prefix: str, count: int, rng: _Random) -> list[str]:
    adjectives = ["Янтарный", "Туманный", "Дальний", "Серебряный", "Сумрачный", "Тихий", "Лунный", "Каменный", "Зелёный", "Ветреный"]
    nouns = ["холм", "путь", "брод", "лес", "предел", "ключ", "поворот", "дол", "исток", "склон"]
    options = [f"{prefix}: {adj} {noun}" for adj in adjectives for noun in nouns]
    rng.shuffle(options)
    return options[:count]


def _region(rooms: list[Room], zone: str, prefix: str, size: int, rng: _Random) -> list[int]:
    start = len(rooms)
    rooms.extend(Room(name, zone) for name in _names(prefix, size * size, rng))
    indices = list(range(start, start + size * size))
    seen = {0}
    stack = [0]
    while stack:
        i = stack[-1]
        candidates = []
        for direction, (dx, dy) in DIRECTIONS.items():
            nx, ny = i % size + dx, i // size + dy
            if 0 <= nx < size and 0 <= ny < size:
                j = ny * size + nx
                if j not in seen:
                    candidates.append((direction, j))
        if not candidates:
            stack.pop()
            continue
        direction, j = candidates[rng.below(len(candidates))]
        rooms[start + i].exits[direction] = start + j
        rooms[start + j].exits[OPPOSITE[direction]] = start + i
        seen.add(j)
        stack.append(j)
    walls = []
    for i in range(size * size):
        for direction in ("east", "south"):
            dx, dy = DIRECTIONS[direction]
            nx, ny = i % size + dx, i // size + dy
            if nx < size and ny < size and direction not in rooms[start + i].exits:
                walls.append((i, direction, ny * size + nx))
    rng.shuffle(walls)
    for i, direction, j in walls[:(2 * size if zone == "overworld" else max(1, size // 2))]:
        rooms[start + i].exits[direction] = start + j
        rooms[start + j].exits[OPPOSITE[direction]] = start + i
    return indices


def generate_world(seed: str | int) -> World:
    """Create four connected regions with reciprocal, reversible entrances."""
    if not isinstance(seed, (str, int)) or isinstance(seed, bool):
        raise ValueError("seed must be a string or integer")
    rng = _Random(str(seed))
    rooms: list[Room] = []
    lands = _region(rooms, "overworld", "Открытые земли", 6, rng)
    mountain = _region(rooms, "mountain", "Гора", 3, rng)
    tower = _region(rooms, "tower", "Башня мага", 2, rng)
    dungeon = _region(rooms, "dungeon", "Подземелье", 3, rng)
    rooms[0].name = "Деревня: Янтарный очаг"
    rooms[0].npc = "Старейшина"

    # Shuffle distinct sites in each region.  Grid edges are always cardinal;
    # region transitions use only up/down, so coordinates do not cross regions.
    land_sites = lands[1:]
    mountain_sites, tower_sites, dungeon_sites = mountain.copy(), tower.copy(), dungeon.copy()
    for sites in (land_sites, mountain_sites, tower_sites, dungeon_sites):
        rng.shuffle(sites)
    mountain_gate, dungeon_gate, herb_giver, bandit_room = land_sites[:4]
    mountain_entry, tower_gate, herb_room, guard_room = mountain_sites[:4]
    tower_entry, wizard_room = tower_sites[:2]
    dungeon_entry, dragon_room = dungeon_sites[:2]

    def link(a: int, direction: str, b: int) -> None:
        rooms[a].exits[direction] = b
        rooms[b].exits[OPPOSITE[direction]] = a

    link(mountain_gate, "up", mountain_entry)
    link(dungeon_gate, "down", dungeon_entry)
    link(tower_gate, "up", tower_entry)
    rooms[herb_giver].npc = "Травница"
    rooms[wizard_room].npc = "Маг"
    rooms[bandit_room].enemy, rooms[bandit_room].enemy_hp = "разбойник", 6
    rooms[guard_room].enemy, rooms[guard_room].enemy_hp = "горный страж", 6
    rooms[dragon_room].enemy, rooms[dragon_room].enemy_hp = "дракон", 16
    quests = [
        Quest("main", "Старейшина", 0, "сердце звезды", dragon_room, True),
        Quest("side", "Травница", herb_giver, "серебряная трава", herb_room, False),
    ]
    return World(rooms, quests, wizard_room, dragon_room)


class Game:
    """Deterministic simulator with partial observations and two distinct quests."""
    def __init__(self, seed: str | int, max_turns: int = DEFAULT_MAX_TURNS):
        if not isinstance(seed, (str, int)) or isinstance(seed, bool):
            raise ValueError("seed must be a string or integer")
        if not isinstance(max_turns, int) or isinstance(max_turns, bool) or max_turns < 1:
            raise ValueError("max_turns must be a positive integer")
        self.seed, self.max_turns = str(seed), max_turns
        self.world = generate_world(self.seed)
        self.position = 0
        self.turn = 0
        self.hp = self.max_hp = 18
        self.potions, self.rations = 3, 2
        self.inventory: list[str] = []
        self.visited = {0}
        self.done = False
        self.terminal_reason: str | None = None
        self.braced = False
        self.ward = False
        self.events: list[dict[str, Any]] = []
        self.message = ("Вы в убежище. Поговорите со старейшиной об основном поручении. "
                        "За открытыми землями расположены гора с башней мага и подземелье дракона. "
                        "Травница может предложить необязательное поручение. Отдых возможен только здесь.")

    def observe(self) -> dict[str, Any]:
        room = self.world.rooms[self.position]
        enemy = None
        if room.enemy_hp > 0:
            intent = ("огненное дыхание" if room.enemy_phase % 2 == 0 else "удар когтями") if room.enemy == "дракон" else "удар"
            enemy = {"name": room.enemy, "hp": room.enemy_hp, "intent": intent}
        return {
            "room": room.name, "zone": room.zone,
            "exits": [direction for direction in ALL_DIRECTIONS if direction in room.exits],
            "npc": room.npc, "enemy": enemy, "hp": self.hp, "max_hp": self.max_hp,
            "inventory": self.inventory.copy(), "potions": self.potions, "rations": self.rations,
            "turn": self.turn, "max_turns": self.max_turns, "message": self.message, "done": self.done,
        }

    def _hurt(self, amount: int) -> int:
        damage = min(self.hp, amount)
        self.hp -= damage
        return damage

    def _response(self, room: Room, defending: bool = False) -> int:
        if room.enemy_hp <= 0:
            return 0
        if defending:
            damage = 1
        elif room.enemy == "дракон" and room.enemy_phase % 2 == 0:
            damage = 4 if self.ward else 6
        else:
            damage = 2
        room.enemy_phase += 1
        return self._hurt(damage)

    def step(self, action: dict[str, Any]) -> dict[str, Any]:
        if self.done:
            raise RuntimeError("game is over")
        self.turn += 1
        room = self.world.rooms[self.position]
        before, valid, damage = self.position, True, 0
        event: dict[str, Any] = {"turn": self.turn, "action": action, "from_room": before}
        kind = action.get("type") if isinstance(action, dict) else None
        main, side = self.world.quests
        if kind == "move":
            direction = action.get("direction")
            if not isinstance(direction, str) or direction not in room.exits:
                valid, self.message = False, "Туда нельзя пройти."
            else:
                if room.enemy_hp > 0:
                    damage = self._hurt(3)
                self.position = room.exits[direction]
                self.visited.add(self.position)
                self.braced = False
                self.message = "Вы перешли в другую локацию."
                if damage:
                    self.message += f" При отступлении вы потеряли {damage} здоровья."
        elif room.enemy_hp > 0 and kind in ("talk", "search", "rest"):
            valid, self.message = False, "Противник мешает действию; сражайтесь или отступите."
        elif kind == "talk":
            if room.npc == "Маг":
                if not self.ward:
                    self.ward = True
                    self.inventory.append("рунический оберег")
                    self.message = ("Маг: возьмите рунический оберег: он снижает урон дыхания дракона на 2. "
                                    "Защита уменьшает любой ответ противника до 1 и усиливает следующую атаку до 5.")
                    event.update(quest_event="ward_received")
                else:
                    self.message = "Маг: оберег уже у вас."
            elif room.npc in ("Старейшина", "Травница"):
                quest = main if room.npc == "Старейшина" else side
                if not quest.accepted:
                    quest.accepted = True
                    self.message = (f"{quest.giver}: найдите {quest.item} в месте «{self.world.rooms[quest.item_room].name}» "
                                    f"и принесите мне сюда, в «{room.name}». Я не повторю поручение.")
                    if quest.key == "main":
                        self.message += (f" Дракон обитает в подземелье; маг в башне, в месте «{self.world.rooms[self.world.wizard_room].name}», "
                                         "подарит оберег: он нужен, чтобы снять печать с реликвии. Вход в горы и вход в подземелье ищите в открытых землях.")
                    else:
                        self.message += " Трава растёт в горах; в награду я дам два зелья."
                    event.update(quest=quest.key, quest_event="accepted")
                elif quest.collected and not quest.completed:
                    quest.completed = True
                    self.inventory.remove(quest.item)
                    if quest.key == "side":
                        self.potions += 2
                    self.message = f"{quest.giver} принимает {quest.item}. Поручение выполнено."
                    if quest.key == "side":
                        self.message += " Вы получили два зелья."
                    event.update(quest=quest.key, quest_event="completed")
                elif quest.completed:
                    self.message = f"{quest.giver}: спасибо за помощь."
                else:
                    self.message = f"{quest.giver}: я уже рассказал вам о своём поручении."
            else:
                valid, self.message = False, "Здесь не с кем говорить."
        elif kind == "search":
            quest = next((q for q in self.world.quests if q.item_room == self.position and q.accepted and not q.collected), None)
            if quest and quest.key == "main" and not self.ward:
                valid, self.message = False, ("Магическая печать закрывает реликвию; чтобы снять её, "
                                              "получите оберег у мага в башне.")
            elif quest:
                quest.collected = True
                self.inventory.append(quest.item)
                self.message = f"Вы нашли предмет: {quest.item}."
                event.update(quest=quest.key, quest_event="collected")
            else:
                self.message = "Вы не нашли ничего полезного."
        elif kind in ("attack", "defend"):
            if room.enemy_hp <= 0:
                valid, self.message = False, "Здесь нет противника."
            elif kind == "attack":
                dealt = 5 if self.braced else 3
                self.braced = False
                room.enemy_hp = max(0, room.enemy_hp - dealt)
                damage = self._response(room)
                self.message = f"Вы нанесли {dealt} урона."
                if damage:
                    self.message += f" Противник ответил: −{damage} здоровья."
                if room.enemy_hp == 0:
                    self.message += " Противник побеждён."
                event["damage_dealt"] = dealt
            else:
                self.braced = True
                damage = self._response(room, defending=True)
                self.message = "Вы защищаетесь: потеряли 1 здоровье, следующая атака сильнее."
        elif kind == "potion":
            if self.potions <= 0 or self.hp == self.max_hp:
                valid, self.message = False, "Зелье сейчас использовать нельзя."
            else:
                self.potions -= 1
                healed = min(6, self.max_hp - self.hp)
                self.hp += healed
                damage = self._response(room)
                self.message = f"Зелье восстановило {healed} здоровья."
                if damage:
                    self.message += f" Противник нанёс {damage} урона."
                event["healed"] = healed
        elif kind == "rest":
            if self.position != 0 or self.rations <= 0 or self.hp == self.max_hp:
                valid, self.message = False, "Отдых доступен только в убежище, при наличии припасов и ран."
            else:
                self.rations -= 1
                healed = min(8, self.max_hp - self.hp)
                self.hp += healed
                self.message = f"Вы отдохнули и восстановили {healed} здоровья."
                event["healed"] = healed
        else:
            valid, self.message = False, "Неизвестное действие."
        event.update(valid=valid, to_room=self.position, damage_taken=damage, hp=self.hp)
        self.events.append(event)
        if self.hp <= 0:
            self.done, self.terminal_reason = True, "death"
        elif main.completed:
            self.done, self.terminal_reason = True, "completed"
        elif self.turn >= self.max_turns:
            self.done, self.terminal_reason = True, "turn_limit"
        return self.observe()

    def result(self) -> dict[str, Any]:
        main, side = self.world.quests
        return {
            "engine_version": ENGINE_VERSION, "seed": self.seed, "turns": self.turn,
            "terminal_reason": self.terminal_reason,
            "quests_completed": int(main.completed) + int(side.completed), "quests_total": 2,
            "main_quest_completed": main.completed, "side_quests_completed": int(side.completed), "side_quests_total": 1,
            "moves": sum(e["valid"] and e["from_room"] != e["to_room"] for e in self.events),
            "invalid_actions": sum(not e["valid"] for e in self.events),
            "rooms_visited": len(self.visited), "rooms_total": len(self.world.rooms),
            "attacks": sum(e["valid"] and isinstance(e["action"], dict) and e["action"].get("type") == "attack" for e in self.events),
            "damage_taken": sum(e["damage_taken"] for e in self.events),
            "potions_used": sum(e["valid"] and isinstance(e["action"], dict) and e["action"].get("type") == "potion" for e in self.events),
            "deaths": int(self.terminal_reason == "death"), "events": self.events.copy(),
        }
