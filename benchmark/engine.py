"""A small deterministic, partially observed adventure environment.

The simulator is intentionally independent of any language model. Private world
state and events are for the evaluator only; agents receive observations.
"""
from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass, field
from typing import Any

ENGINE_VERSION = "0.1.0"
DIRECTIONS = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}
OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}
ROOM_NAMES = [
    "Тихая пристань", "Башня пепла", "Зал часов", "Мшистый двор", "Старая кузница",
    "Зал масок", "Лунный колодец", "Забытая библиотека", "Каменный сад", "Зеркальная галерея",
    "Склеп ворона", "Рыночный перекрёсток", "Разбитая обсерватория", "Зал корней",
    "Красные ворота", "Зал фонарей",
]
PEOPLE = ["Альма", "Берен", "Веста", "Горн", "Дара", "Елисей", "Жара", "Зорин"]
ITEMS = ["серебряный ключ", "янтарная печать", "хрустальная сфера", "медный компас",
         "книга приливов", "лунный амулет", "железная корона", "нефритовый кубок"]
ENEMIES = ["страж теней", "каменный голем", "лесной разбойник", "склепный паук"]


class _Random:
    """SHA-256 counter stream; stable across Python versions and processes."""
    def __init__(self, seed: str):
        self.seed = seed
        self.counter = 0

    def below(self, n: int) -> int:
        # Rejection sampling avoids modulo bias; the draw order is part of the version.
        if n <= 0:
            raise ValueError("empty range")
        limit = (1 << 256) - (1 << 256) % n
        while True:
            raw = f"adventure:{ENGINE_VERSION}:{self.seed}:{self.counter}".encode("utf-8")
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
    exits: dict[str, int] = field(default_factory=dict)
    npc: str | None = None
    enemy: str | None = None
    enemy_hp: int = 0


@dataclass
class Quest:
    giver: str
    giver_room: int
    item: str
    item_room: int
    accepted: bool = False
    collected: bool = False
    completed: bool = False


@dataclass
class World:
    rooms: list[Room]
    quests: list[Quest]


def generate_world(seed: str | int) -> World:
    """Generate a connected 4x4 maze, six distinct quest sites and three guards."""
    rng = _Random(str(seed))
    names = ROOM_NAMES.copy()
    rng.shuffle(names)
    rooms = [Room(name) for name in names]
    seen = {0}
    stack = [0]
    while stack:
        current = stack[-1]
        x, y = current % 4, current // 4
        candidates = []
        for direction, (dx, dy) in DIRECTIONS.items():
            nx, ny = x + dx, y + dy
            nxt = ny * 4 + nx
            if 0 <= nx < 4 and 0 <= ny < 4 and nxt not in seen:
                candidates.append((direction, nxt))
        if not candidates:
            stack.pop()
            continue
        direction, nxt = candidates[rng.below(len(candidates))]
        rooms[current].exits[direction] = nxt
        rooms[nxt].exits[OPPOSITE[direction]] = current
        seen.add(nxt)
        stack.append(nxt)

    # Add a few loops, avoiding a simple tree traversal as the only solution.
    walls = []
    for i in range(16):
        for direction in ("east", "south"):
            dx, dy = DIRECTIONS[direction]
            nx, ny = i % 4 + dx, i // 4 + dy
            if nx < 4 and ny < 4 and direction not in rooms[i].exits:
                walls.append((i, direction, ny * 4 + nx))
    rng.shuffle(walls)
    for i, direction, j in walls[:3]:
        rooms[i].exits[direction] = j
        rooms[j].exits[OPPOSITE[direction]] = i

    sites = list(range(1, 16))
    people, items = PEOPLE.copy(), ITEMS.copy()
    rng.shuffle(sites)
    rng.shuffle(people)
    rng.shuffle(items)
    quests = []
    for index in range(3):
        giver_room, item_room = sites[index], sites[index + 3]
        npc, item = people[index], items[index]
        rooms[giver_room].npc = npc
        rooms[item_room].enemy = ENEMIES[rng.below(len(ENEMIES))]
        rooms[item_room].enemy_hp = 6 + rng.below(3)
        quests.append(Quest(npc, giver_room, item, item_room))
    return World(rooms, quests)


def shortest_distance(world: World, start: int, end: int) -> int:
    """Evaluator-only shortest path; never included in an agent observation."""
    queue = deque([(start, 0)])
    seen = {start}
    while queue:
        room, distance = queue.popleft()
        if room == end:
            return distance
        for nxt in world.rooms[room].exits.values():
            if nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, distance + 1))
    raise ValueError("world is disconnected")


class Game:
    """Turn-based environment. Observations deliberately omit the quest journal.

    Actions are dictionaries with a type; movement also requires a direction.
    Events and world are privileged evaluator data, not model input.
    """
    def __init__(self, seed: str | int, max_turns: int = 120):
        if not isinstance(seed, (str, int)) or isinstance(seed, bool):
            raise ValueError("seed must be a string or integer")
        if not isinstance(max_turns, int) or isinstance(max_turns, bool) or max_turns < 1:
            raise ValueError("max_turns must be a positive integer")
        self.seed = str(seed)
        self.max_turns = max_turns
        self.world = generate_world(self.seed)
        self.position = 0
        self.turn = 0
        self.hp = self.max_hp = 18
        self.potions = 3
        self.rations = 2
        self.inventory: list[str] = []
        self.visited = {0}
        self.done = False
        self.terminal_reason: str | None = None
        self.message = ("Вы в убежище. Найдите трёх жителей, выполните их поручения и верните им вещи. "
                        "Задание сообщается только один раз. Передвигайтесь по выходам; "
                        "здесь можно отдохнуть. У вас три зелья и два припаса.")
        self.braced = False
        self.events: list[dict[str, Any]] = []

    def observe(self) -> dict[str, Any]:
        room = self.world.rooms[self.position]
        return {
            "room": room.name,
            "exits": [direction for direction in DIRECTIONS if direction in room.exits],
            "npc": room.npc,
            "enemy": {"name": room.enemy, "hp": room.enemy_hp} if room.enemy_hp > 0 else None,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "inventory": self.inventory.copy(),
            "potions": self.potions,
            "rations": self.rations,
            "turn": self.turn,
            "max_turns": self.max_turns,
            "message": self.message,
            "done": self.done,
        }

    def _hurt(self, amount: int) -> int:
        damage = min(self.hp, amount)
        self.hp -= damage
        return damage

    def step(self, action: dict[str, Any]) -> dict[str, Any]:
        if self.done:
            raise RuntimeError("game is over")
        self.turn += 1
        room = self.world.rooms[self.position]
        before = self.position
        damage = 0
        valid = True
        event: dict[str, Any] = {"turn": self.turn, "action": action, "from_room": before}
        kind = action.get("type") if isinstance(action, dict) else None

        if kind == "move":
            direction = action.get("direction")
            if not isinstance(direction, str) or direction not in room.exits:
                valid, self.message = False, "Туда нельзя пройти."
            else:
                if room.enemy_hp > 0:
                    damage = self._hurt(2)
                self.position = room.exits[direction]
                self.visited.add(self.position)
                self.braced = False
                self.message = "Вы перешли в другую комнату."
                if damage:
                    self.message += f" При отступлении вы потеряли {damage} здоровья."
        elif kind == "talk":
            quest = next((q for q in self.world.quests if q.giver_room == self.position), None)
            if not quest:
                valid, self.message = False, "Здесь не с кем говорить."
            elif not quest.accepted:
                quest.accepted = True
                self.message = (f"{quest.giver}: найдите {quest.item} в месте «{self.world.rooms[quest.item_room].name}» "
                                f"и принесите мне сюда, в «{room.name}». Я не повторю поручение.")
                event.update(quest=quest.giver, quest_event="accepted")
            elif quest.collected and not quest.completed:
                quest.completed = True
                self.inventory.remove(quest.item)
                self.message = f"{quest.giver} принимает {quest.item}. Поручение выполнено."
                event.update(quest=quest.giver, quest_event="completed")
            elif quest.completed:
                self.message = f"{quest.giver}: спасибо за помощь."
            else:
                self.message = f"{quest.giver}: я уже рассказал вам о своём поручении."
        elif kind == "search":
            if room.enemy_hp > 0:
                valid, self.message = False, "Страж мешает обыскать комнату."
            else:
                quest = next((q for q in self.world.quests if q.item_room == self.position
                              and q.accepted and not q.collected), None)
                if quest:
                    quest.collected = True
                    self.inventory.append(quest.item)
                    self.message = f"Вы нашли предмет: {quest.item}."
                    event.update(quest=quest.giver, quest_event="collected")
                else:
                    self.message = "Вы не нашли ничего полезного."
        elif kind in ("attack", "defend"):
            if room.enemy_hp <= 0:
                valid, self.message = False, "Здесь нет противника."
            elif kind == "attack":
                dealt = 5 if self.braced else 3
                self.braced = False
                room.enemy_hp = max(0, room.enemy_hp - dealt)
                damage = self._hurt(2) if room.enemy_hp > 0 else 0
                self.message = f"Вы нанесли {dealt} урона."
                if damage:
                    self.message += f" Противник ответил: −{damage} здоровья."
                if room.enemy_hp == 0:
                    self.message += " Противник побеждён."
                event["damage_dealt"] = dealt
            else:
                self.braced = True
                damage = self._hurt(1)
                self.message = "Вы защищаетесь: потеряли 1 здоровье, следующая атака сильнее."
        elif kind == "potion":
            if self.potions <= 0 or self.hp == self.max_hp:
                valid, self.message = False, "Зелье сейчас использовать нельзя."
            else:
                self.potions -= 1
                healed = min(6, self.max_hp - self.hp)
                self.hp += healed
                damage = self._hurt(2) if room.enemy_hp > 0 else 0
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
        elif all(q.completed for q in self.world.quests):
            self.done, self.terminal_reason = True, "completed"
        elif self.turn >= self.max_turns:
            self.done, self.terminal_reason = True, "turn_limit"
        return self.observe()

    def result(self) -> dict[str, Any]:
        return {
            "engine_version": ENGINE_VERSION,
            "seed": self.seed,
            "turns": self.turn,
            "terminal_reason": self.terminal_reason,
            "quests_completed": sum(q.completed for q in self.world.quests),
            "quests_total": len(self.world.quests),
            "moves": sum(e["valid"] and e["from_room"] != e["to_room"] for e in self.events),
            "invalid_actions": sum(not e["valid"] for e in self.events),
            "rooms_visited": len(self.visited),
            "rooms_total": len(self.world.rooms),
            "attacks": sum(e["valid"] and isinstance(e["action"], dict) and e["action"].get("type") == "attack" for e in self.events),
            "damage_taken": sum(e["damage_taken"] for e in self.events),
            "potions_used": 3 - self.potions,
            "deaths": int(self.terminal_reason == "death"),
            "events": self.events.copy(),
        }
