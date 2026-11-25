"""A seeded caravan-city scenario with many residents and side quests.

The city stresses quest memory and interference rather than combat: ten fetch
quests from lookalike residents with lookalike item names, plus rumour NPCs
whose gossip may be outdated. All world internals and event records are
evaluator-only; the model receives only ``observe()`` and information it has
previously observed.
"""
from __future__ import annotations

from collections import deque
import hashlib
from dataclasses import dataclass, field
from typing import Any

ENGINE_VERSION = "caravan-0.2.0"
MIN_MAX_TURNS = 240
TURN_SLACK = 2  # default turn limit is TURN_SLACK times the greedy oracle estimate
DIRECTIONS = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}
OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}
GRID = 8
DISTRICTS = ("Рынок", "Доки", "Ремесленный квартал", "Старый город")

SYSTEM_PROMPT = """You are playing a turn-based fantasy adventure in a caravan city of four
districts. The guildmaster at the caravanserai gives the main quest; many
residents offer optional fetch quests with stated rewards. Quest details are
given only once, so remember them: similar names and items are easily confused.
You see only the current location. Each turn answer with exactly one JSON
object and no other text. Actions: {"type":"move","direction":
"north|south|east|west"}, {"type":"talk"}, {"type":"search"},
{"type":"attack"}, {"type":"defend"}, {"type":"potion"}, {"type":"rest"}.
Use only exits listed in the current observation. Search a quest location only
after accepting its quest. Attack deals 3 damage; defend costs 1 HP and makes
the next attack deal 5. Enemies deal 2 damage when they survive an attack,
when you use a potion in combat, or when you retreat (move away). A potion
heals up to 6 HP. Rest at the caravanserai consumes one ration and restores
8 HP. The game ends when every quest is completed. Your current observation
is supplied as JSON."""

ADJECTIVES = ["Янтарный", "Туманный", "Дальний", "Серебряный", "Сумрачный", "Тихий", "Лунный", "Каменный"]
NOUNS = ["ряд", "двор", "переулок", "тупик", "мост", "колодец", "дворик", "закоулок"]
RESIDENTS = ["Альдар", "Альбина", "Боян", "Борина", "Велимир", "Велина", "Дарко",
             "Дарина", "Милко", "Милана", "Ратко", "Ратина", "Желана"]
ITEM_ADJECTIVES = ["медная", "серебряная", "янтарная", "лунная", "костяная"]
ITEM_NOUNS = ["монета", "печать", "фибула", "чаша", "пряжка"]
GUARDS = ["страж склада", "грабитель", "дикий пёс"]


class _Random:
    """Versioned SHA-256 counter generator, independent of Python's hash seed."""
    def __init__(self, seed: str):
        self.seed = seed
        self.counter = 0

    def below(self, n: int) -> int:
        # Rejection sampling avoids modulo bias; the draw order is part of the version.
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
    district: str
    exits: dict[str, int] = field(default_factory=dict)
    npc: str | None = None
    enemy: str | None = None
    enemy_hp: int = 0


@dataclass
class Quest:
    key: str
    giver: str
    giver_room: int
    item: str
    item_room: int
    reward: str | None
    accepted: bool = False
    collected: bool = False
    completed: bool = False


@dataclass
class World:
    rooms: list[Room]
    quests: list[Quest]
    rumors: dict[int, int]  # flavour NPC room -> quest index the rumour mentions


def _district(index: int) -> str:
    x, y = index % GRID, index // GRID
    return DISTRICTS[(x >= GRID // 2) + 2 * (y >= GRID // 2)]


def generate_world(seed: str | int) -> World:
    """Create a connected 8x8 city with ten quest sites and mild guards."""
    if not isinstance(seed, (str, int)) or isinstance(seed, bool):
        raise ValueError("seed must be a string or integer")
    rng = _Random(str(seed))
    rooms: list[Room] = []
    for district in DISTRICTS:
        options = [f"{district}: {adj} {noun}" for adj in ADJECTIVES for noun in NOUNS]
        rng.shuffle(options)
        rooms.extend(Room(name, district) for name in options[:GRID * GRID // 4])
    # District quadrants are contiguous, but the shuffled name assignment above
    # is per district; reorder rooms back onto the grid by quadrant.
    by_district = {district: rooms[i * 16:(i + 1) * 16] for i, district in enumerate(DISTRICTS)}
    ordered: list[Room] = []
    cursors = {district: 0 for district in DISTRICTS}
    for index in range(GRID * GRID):
        district = _district(index)
        ordered.append(by_district[district][cursors[district]])
        cursors[district] += 1
    rooms = ordered
    rooms[0].name = "Караван-сарай «Янтарный верблюд»"
    rooms[0].npc = "Бургомистр"

    seen, stack = {0}, [0]
    while stack:
        current = stack[-1]
        x, y = current % GRID, current // GRID
        candidates = []
        for direction, (dx, dy) in DIRECTIONS.items():
            nx, ny = x + dx, y + dy
            nxt = ny * GRID + nx
            if 0 <= nx < GRID and 0 <= ny < GRID and nxt not in seen:
                candidates.append((direction, nxt))
        if not candidates:
            stack.pop()
            continue
        direction, nxt = candidates[rng.below(len(candidates))]
        rooms[current].exits[direction] = nxt
        rooms[nxt].exits[OPPOSITE[direction]] = current
        seen.add(nxt)
        stack.append(nxt)
    walls = []
    for i in range(GRID * GRID):
        for direction in ("east", "south"):
            dx, dy = DIRECTIONS[direction]
            nx, ny = i % GRID + dx, i // GRID + dy
            if nx < GRID and ny < GRID and direction not in rooms[i].exits:
                walls.append((i, direction, ny * GRID + nx))
    rng.shuffle(walls)
    for i, direction, j in walls[:2 * GRID]:
        rooms[i].exits[direction] = j
        rooms[j].exits[OPPOSITE[direction]] = i

    sites = list(range(1, GRID * GRID))
    names, items = RESIDENTS.copy(), [f"{adj} {noun}" for adj in ITEM_ADJECTIVES for noun in ITEM_NOUNS]
    rng.shuffle(sites)
    rng.shuffle(names)
    rng.shuffle(items)
    side_givers, flavour = sites[:9], sites[9:13]
    item_rooms, bandit_rooms = sites[13:23], sites[23:25]
    quests = [Quest("main", "Бургомистр", 0, items[0], item_rooms[0], None)]
    for index in range(9):
        rooms[side_givers[index]].npc = names[index]
        quests.append(Quest("side", names[index], side_givers[index],
                            items[index + 1], item_rooms[index + 1], None))
    rumours = {}
    for offset, room in enumerate(flavour):
        rooms[room].npc = names[9 + offset]
        rumours[room] = rng.below(len(quests))

    guarded = [True] * 5 + [False] * 4
    rng.shuffle(guarded)
    rooms[quests[0].item_room].enemy, rooms[quests[0].item_room].enemy_hp = "страж реликвии", 8
    for index, quest in enumerate(quests[1:]):
        if guarded[index]:
            rooms[quest.item_room].enemy = GUARDS[rng.below(len(GUARDS))]
            rooms[quest.item_room].enemy_hp = 5 + rng.below(2)
    for room in bandit_rooms:
        rooms[room].enemy, rooms[room].enemy_hp = "разбойник", 6

    rewards: list[str | None] = ["potion"] * 3 + ["ration"] * 3 + [None] * 3
    rng.shuffle(rewards)
    for index, quest in enumerate(quests[1:]):
        quest.reward = rewards[index]
    return World(rooms, quests, rumours)


def _distances(world: World, start: int) -> list[int]:
    """Evaluator-only BFS distances; never included in an agent observation."""
    dist = [-1] * len(world.rooms)
    dist[start] = 0
    queue = deque([start])
    while queue:
        room = queue.popleft()
        for nxt in world.rooms[room].exits.values():
            if dist[nxt] < 0:
                dist[nxt] = dist[room] + 1
                queue.append(nxt)
    return dist


def oracle_turns(world: World) -> int:
    """Greedy full-completion route estimate in turns; evaluator-only.

    Nearest-next-objective routing with plain attacks; a lower bound on a
    careful player's needs, so the default budget scales from it.
    """
    position, turns = 0, 0
    accepted: set[int] = set()
    collected: set[int] = set()
    completed: set[int] = set()
    while len(completed) < len(world.quests):
        best = None
        for index, quest in enumerate(world.quests):
            if index in completed:
                continue
            if index not in accepted:
                room, cost = quest.giver_room, 1
            elif index not in collected:
                guard = world.rooms[quest.item_room].enemy_hp
                room, cost = quest.item_room, 1 + -(-guard // 3)  # search + attacks
            else:
                room, cost = quest.giver_room, 1
            distance = _distances(world, position)[room] + cost
            if best is None or distance < best[0]:
                best = (distance, room, index)
        turns += best[0]
        position = best[1]
        index = best[2]
        if index not in accepted:
            accepted.add(index)
        elif index not in collected:
            collected.add(index)
        else:
            completed.add(index)
    return turns


class Game:
    """Deterministic simulator with partial observations and ten distinct quests."""
    def __init__(self, seed: str | int, max_turns: int | None = None):
        if not isinstance(seed, (str, int)) or isinstance(seed, bool):
            raise ValueError("seed must be a string or integer")
        if max_turns is not None and (not isinstance(max_turns, int)
                                      or isinstance(max_turns, bool) or max_turns < 1):
            raise ValueError("max_turns must be a positive integer")
        self.seed = str(seed)
        self.world = generate_world(self.seed)
        estimate = oracle_turns(self.world)
        self.oracle_estimate = estimate
        self.max_turns = max(MIN_MAX_TURNS, TURN_SLACK * estimate) if max_turns is None else max_turns
        self.position = 0
        self.turn = 0
        self.hp = self.max_hp = 22
        self.potions, self.rations = 4, 2
        self.inventory: list[str] = []
        self.visited = {0}
        self.done = False
        self.terminal_reason: str | None = None
        self.braced = False
        self.rumours_heard: set[int] = set()
        self.events: list[dict[str, Any]] = []
        self.message = ("Вы в караван-сарае. Поговорите с бургомистром об основном поручении. "
                        "Жители города предлагают необязательные поручения с наградой; "
                        "каждое поручение сообщается только один раз. Отдых возможен только здесь.")

    def observe(self) -> dict[str, Any]:
        room = self.world.rooms[self.position]
        return {
            "room": room.name, "district": room.district,
            "exits": [direction for direction in DIRECTIONS if direction in room.exits],
            "npc": room.npc,
            "enemy": {"name": room.enemy, "hp": room.enemy_hp} if room.enemy_hp > 0 else None,
            "hp": self.hp, "max_hp": self.max_hp,
            "inventory": self.inventory.copy(), "potions": self.potions, "rations": self.rations,
            "turn": self.turn, "max_turns": self.max_turns, "message": self.message, "done": self.done,
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
        before, valid, damage = self.position, True, 0
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
                self.message = "Вы перешли в другую локацию."
                if damage:
                    self.message += f" При отступлении вы потеряли {damage} здоровья."
        elif kind == "talk":
            quest = next((q for q in self.world.quests if q.giver_room == self.position), None)
            if quest is not None:
                if not quest.accepted:
                    quest.accepted = True
                    self.message = (f"{quest.giver}: найдите {quest.item} в месте «{self.world.rooms[quest.item_room].name}» "
                                    f"и принесите мне сюда, в «{room.name}». Я не повторю поручение.")
                    if quest.reward == "potion":
                        self.message += " В награду дам зелье."
                    elif quest.reward == "ration":
                        self.message += " В награду дам припас."
                    event.update(quest=quest.key, quest_event="accepted")
                elif quest.collected and not quest.completed:
                    quest.completed = True
                    self.inventory.remove(quest.item)
                    if quest.reward == "potion":
                        self.potions += 1
                    elif quest.reward == "ration":
                        self.rations += 1
                    self.message = f"{quest.giver} принимает {quest.item}. Поручение выполнено."
                    if quest.reward == "potion":
                        self.message += " Вы получили зелье."
                    elif quest.reward == "ration":
                        self.message += " Вы получили припас."
                    event.update(quest=quest.key, quest_event="completed")
                elif quest.completed:
                    self.message = f"{quest.giver}: спасибо за помощь."
                else:
                    self.message = f"{quest.giver}: я уже рассказал вам о своём поручении."
            elif self.position in self.world.rumors:
                if self.position not in self.rumours_heard:
                    self.rumours_heard.add(self.position)
                    target = self.world.quests[self.world.rumors[self.position]]
                    self.message = (f"{room.npc}: говорят, {target.item} можно найти "
                                    f"в месте «{self.world.rooms[target.item_room].name}». "
                                    "Только не спрашивайте, откуда я знаю.")
                else:
                    self.message = f"{room.npc}: я уже всё рассказал."
            else:
                valid, self.message = False, "Здесь не с кем говорить."
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
                valid, self.message = False, "Отдых доступен только в караван-сарае, при наличии припасов и ран."
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
        sides = self.world.quests[1:]
        return {
            "engine_version": ENGINE_VERSION, "seed": self.seed, "turns": self.turn,
            "terminal_reason": self.terminal_reason,
            "quests_completed": sum(q.completed for q in self.world.quests),
            "quests_total": len(self.world.quests),
            "main_quest_completed": self.world.quests[0].completed,
            "side_quests_completed": sum(q.completed for q in sides), "side_quests_total": len(sides),
            "oracle_estimate": self.oracle_estimate,
            "moves": sum(e["valid"] and e["from_room"] != e["to_room"] for e in self.events),
            "invalid_actions": sum(not e["valid"] for e in self.events),
            "rooms_visited": len(self.visited), "rooms_total": len(self.world.rooms),
            "attacks": sum(e["valid"] and isinstance(e["action"], dict) and e["action"].get("type") == "attack" for e in self.events),
            "damage_taken": sum(e["damage_taken"] for e in self.events),
            "potions_used": sum(e["valid"] and isinstance(e["action"], dict) and e["action"].get("type") == "potion" for e in self.events),
            "deaths": int(self.terminal_reason == "death"), "events": self.events.copy(),
        }
