"""Observation-only baseline for configurable expeditions.

This is a reference heuristic, not an oracle: it keeps a graph from observed
transitions and reads the same NPC text and topic lists as a model. It does not
read the engine, seed, private map or quest plan. Performance should not be
interpreted as a language-model measurement.
"""
from __future__ import annotations

from collections import deque
import re
from typing import Any

_REVERSE = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east',
            'up': 'down', 'down': 'up'}
_FACT = re.compile(r'Поручение «(?P<quest>[^»]+)», шаг (?P<step>\d+): (?P<action>.*?) в месте «(?P<room>[^»]+)»\.')
_DEPS = re.compile(r'«([^»]+)», шаг (\d+)')


class ExpeditionBaselineAgent:
    """Explore observed exits, ask visible topics and pursue known objectives."""

    def __init__(self) -> None:
        self.graph: dict[str, dict[str, str]] = {}
        self.exits: dict[str, list[str]] = {}
        self.previous_observation: dict[str, Any] | None = None
        self.previous_action: dict[str, Any] | None = None
        self.refuge: str | None = None
        self.seen_npcs: set[str] = set()
        self.asked: set[tuple[str, str]] = set()
        self.tasks: dict[tuple[str, int], dict[str, Any]] = {}
        self.history: list[dict[str, Any]] = []
        self.done: dict[tuple[str, int], int] = {}
        self.stalled_targets: set[tuple[str, int]] = set()
        self.braced = False
        self.dragon_rooms: set[str] = set()
        # Only effects actually displayed by the opponent are remembered.
        self.enemy_intents: dict[str, dict[str, int]] = {}

    def _update_graph(self, obs: dict[str, Any]) -> None:
        room = obs['room']
        self.graph.setdefault(room, {})
        self.exits[room] = list(obs.get('exits', []))
        prev, action = self.previous_observation, self.previous_action
        if not prev or not action:
            return
        origin = prev['room']
        kind = action.get('type')
        if kind == 'move' and room != origin:
            direction = action.get('direction')
            if direction in _REVERSE:
                self.graph.setdefault(origin, {})[direction] = room
                self.graph[room][_REVERSE[direction]] = origin
            self.braced = False
        if kind == 'defend' and obs.get('enemy'):
            self.braced = True
        if kind == 'attack':
            self.braced = False
        if kind == 'talk' and prev.get('npc'):
            self.history.append({'action': 'talk', 'room': origin, 'target': prev['npc'], 'turn': obs['turn']})
        if kind == 'search' and (set(obs.get('inventory', [])) - set(prev.get('inventory', []))):
            self.history.append({'action': 'search', 'room': origin,
                                 'target': sorted(set(obs['inventory']) - set(prev['inventory']))[0],
                                 'turn': obs['turn']})
        if kind in ('attack', 'ability') and prev.get('enemy') and not obs.get('enemy'):
            enemy = prev['enemy']
            self.history.append({'action': 'defeat', 'room': origin, 'target': enemy.get('name'), 'turn': obs['turn']})

    def _remember_fact(self, text: str) -> None:
        match = _FACT.search(text)
        if not match:
            return
        key = (match['quest'], int(match['step']))
        action = match['action']
        if action.startswith('поговорить с персонажем «'):
            kind = 'talk'
        elif action.startswith('найти предмет «'):
            kind = 'search'
        elif action.startswith('победить противника «'):
            kind = 'defeat'
        else:
            return
        target_match = re.search(r'«([^»]+)»', action)
        if not target_match:
            return
        deps_text = text[match.end():]
        dependencies = {(name, int(number)) for name, number in _DEPS.findall(deps_text)}
        self.tasks[key] = {'action': kind, 'target': target_match.group(1), 'room': match['room'],
                           'requires': dependencies}
        self._reconcile()

    def _reconcile(self) -> None:
        # Reconstruct only facts derivable from our own history and visible NPC
        # hints. Defeating a foe is persistent even if the quest was not yet
        # accepted. Wizard visits are persistent when no scout prerequisite is
        # mentioned; otherwise a later visit is required.
        changed = True
        while changed:
            changed = False
            for key, task in self.tasks.items():
                if key in self.done or any(dep not in self.done for dep in task['requires']):
                    continue
                threshold = max((self.done[dep] for dep in task['requires']), default=0)
                sticky = task['action'] == 'defeat' or (
                    task['action'] == 'talk' and task['target'] == 'Маг'
                    and not any('следопыт' in dep[0].casefold() for dep in task['requires']))
                for event in self.history:
                    if (event['action'] == task['action'] and event['room'] == task['room']
                            and event['target'] == task['target'] and (sticky or event['turn'] >= threshold)):
                        self.done[key] = max(event['turn'], threshold)
                        changed = True
                        break

    def _route(self, room: str, targets: set[str], *, frontier: bool = False,
               blocked: set[str] | None = None) -> str | None:
        queue = deque([(room, None)])
        visited = {room}
        blocked = blocked or set()
        while queue:
            current, first = queue.popleft()
            if first is not None and current in targets:
                return first
            for direction in self.exits.get(current, []):
                destination = self.graph.get(current, {}).get(direction)
                if destination is None:
                    if frontier:
                        return first or direction
                elif destination not in visited and destination not in blocked:
                    visited.add(destination)
                    queue.append((destination, first or direction))
        return None

    def _combat(self, obs: dict[str, Any]) -> dict[str, Any]:
        enemy = obs['enemy']
        intent = enemy.get('intent') or {}
        if isinstance(intent, str):
            intent = {'name': intent, 'damage': 6 if intent == 'огненное дыхание' else 2}
        damage = intent.get('damage', 2)
        if not isinstance(damage, int):
            damage = 2
        enemy_name = enemy.get('name')
        intent_id = intent.get('id')
        if isinstance(enemy_name, str) and isinstance(intent_id, str):
            self.enemy_intents.setdefault(enemy_name, {})[intent_id] = damage
        if enemy_name == 'дракон':
            planned = self._dragon_plan(obs, intent_id)
            if planned is not None:
                return planned
        character = obs.get('character') or {}
        abilities = character.get('abilities') or []
        usable = next((a for a in abilities if a.get('ready')), None)
        hp, max_hp = obs.get('hp', 0), obs.get('max_hp', 18)
        hp_enemy = enemy.get('hp', 99)
        cap = intent.get('physical_damage_cap')
        fire_cap = intent.get('fire_damage_cap')
        defend_damage = intent.get('damage_if_defending', min(damage, 1))
        if not isinstance(defend_damage, int):
            defend_damage = min(damage, 1)
        ordinary_damage = 5 if self.braced else 3
        if isinstance(cap, int):
            ordinary_damage = min(ordinary_damage, cap)
        if hp_enemy <= ordinary_damage:
            return {'type': 'attack'}
        fire_damage = min(7, fire_cap) if isinstance(fire_cap, int) else 7
        heavy_damage = min(6, cap) if isinstance(cap, int) else 6
        if usable and usable.get('id') == 'fire_bolt' and hp_enemy <= fire_damage:
            return {'type': 'ability', 'ability': 'fire_bolt'}
        if usable and usable.get('id') == 'heavy_strike' and hp_enemy <= heavy_damage:
            return {'type': 'ability', 'ability': 'heavy_strike'}
        if usable and usable.get('id') == 'fire_bolt' and fire_damage > ordinary_damage and hp > damage:
            return {'type': 'ability', 'ability': 'fire_bolt'}
        if usable and usable.get('id') == 'heavy_strike' and heavy_damage > ordinary_damage and hp > damage:
            return {'type': 'ability', 'ability': 'heavy_strike'}
        # A potion or first aid triggers an enemy response. Do not spend one
        # if incoming damage cancels all healing; defend now and heal on a
        # later, safer phase. When defending itself would kill, healing that
        # leaves the player alive is preferable even without a net gain.
        def useful_heal(amount: int) -> bool:
            after = min(max_hp, hp + amount) - damage
            return after > 0 and (after > hp or hp <= defend_damage)

        # Healing while a blocking enemy deals little damage is substantially
        # safer than waiting for its heavy strike. Never sit in a defend loop:
        # once braced, attack the first exposed phase if we can survive it.
        if isinstance(cap, int) and cap <= 1 and hp <= 8:
            if usable and usable.get('id') == 'first_aid' and hp < max_hp and useful_heal(5):
                return {'type': 'ability', 'ability': 'first_aid'}
            if obs.get('potions', 0) and hp <= max_hp - 6 and useful_heal(6):
                return {'type': 'potion'}
        if self.braced and (not isinstance(cap, int) or cap > 1) and hp > damage:
            return {'type': 'attack'}
        if hp <= damage + 2 and usable and usable.get('id') == 'first_aid' and hp < max_hp and useful_heal(5):
            return {'type': 'ability', 'ability': 'first_aid'}
        if hp <= damage + 2 and obs.get('potions', 0) and hp < max_hp and useful_heal(6):
            return {'type': 'potion'}
        if hp <= damage or damage >= 4 or (isinstance(cap, int) and cap <= 1):
            return {'type': 'defend'}
        return {'type': 'attack'}

    def _dragon_plan(self, obs: dict[str, Any], phase: Any) -> dict[str, Any] | None:
        """Find a survivable sequence using only already-observed dragon phases.

        This heuristic assumes the two observed intents alternate; it does not
        predict damage until both attacks have actually been seen. Search uses
        only current public HP, potions and ability/cooldown details.
        """
        known = self.enemy_intents.get('дракон', {})
        if phase not in ('breath', 'claws') or not all(p in known for p in ('breath', 'claws')):
            return None
        character = obs.get('character') or {}
        abilities = character.get('abilities') or []
        ability = abilities[0] if abilities else {}
        ability_id = ability.get('id')
        energy = character.get('energy', 0)
        cooldown = ability.get('cooldown_remaining', 0)
        cost = ability.get('energy_cost', 0)
        cooldown_turns = ability.get('cooldown_turns', 0)
        if not all(isinstance(x, int) and not isinstance(x, bool)
                   for x in (energy, cooldown, cost, cooldown_turns)):
            return None
        max_hp = obs.get('max_hp', 18)
        enemy_hp = obs['enemy'].get('hp', 0)
        start = (obs.get('hp', 0), enemy_hp, phase, self.braced,
                 obs.get('potions', 0), energy, cooldown)
        queue = deque([(start, None)])
        seen = {start}
        while queue:
            (hp, foe_hp, current, braced, potions, remaining, cd), first = queue.popleft()
            strike = 5 if braced else 3
            options = [({'type': 'attack'}, strike, 0, False, 0, 0, False),
                       ({'type': 'defend'}, 0, 0, True, 0, 0, False)]
            if ability_id in ('fire_bolt', 'heavy_strike') and remaining >= cost and cd == 0:
                options.append(({'type': 'ability', 'ability': ability_id},
                                7 if ability_id == 'fire_bolt' else 6, 0, braced, 0, cost, True))
            if ability_id == 'first_aid' and remaining >= cost and cd == 0 and hp < max_hp:
                options.append(({'type': 'ability', 'ability': ability_id}, 0, 5, braced, 0, cost, True))
            if potions > 0 and hp < max_hp:
                options.append(({'type': 'potion'}, 0, 6, braced, 1, 0, False))
            for action, dealt, healed, next_braced, spent_potion, spent_energy, used_ability in options:
                first_action = first or action
                if dealt >= foe_hp:
                    return first_action
                after_hp = min(max_hp, hp + healed)
                incoming = min(known[current], 1) if action['type'] == 'defend' else known[current]
                after_hp -= incoming
                if after_hp <= 0:
                    continue
                next_cd = cooldown_turns if used_ability else max(0, cd - 1)
                state = (after_hp, foe_hp - dealt, 'claws' if current == 'breath' else 'breath',
                         next_braced, potions - spent_potion, remaining - spent_energy, next_cd)
                if state not in seen:
                    seen.add(state)
                    queue.append((state, first_action))
        return None

    def act(self, obs: dict[str, Any]) -> dict[str, Any]:
        """Choose an action from the visible observation and own memory."""
        room = obs['room']
        if self.refuge is None:
            self.refuge = room
        self._update_graph(obs)
        self._remember_fact(str(obs.get('message', '')))
        self._reconcile()
        action = self._choose(obs)
        self.previous_observation = obs
        self.previous_action = action
        return action

    def _choose(self, obs: dict[str, Any]) -> dict[str, Any]:
        room = obs['room']
        if obs.get('enemy'):
            # The elder tells us the ward reduces dragon breath. When we
            # stumble into its lair without the ward, retreat along the known
            # entrance rather than commit to a much more dangerous fight.
            if (obs['enemy'].get('name') == 'дракон'
                    and 'рунический оберег' not in obs.get('inventory', [])):
                self.dragon_rooms.add(room)
                previous = self.previous_observation
                if previous and obs.get('hp', 0) > 3:
                    back = next((direction for direction, target in self.graph.get(room, {}).items()
                                 if target == previous['room']), None)
                    if back:
                        return {'type': 'move', 'direction': back}
            return self._combat(obs)
        if room == self.refuge and obs.get('rations', 0) and obs.get('hp', 0) <= obs.get('max_hp', 0) // 2:
            return {'type': 'rest'}
        character = obs.get('character') or {}
        for ability in character.get('abilities') or []:
            if ability.get('id') == 'first_aid' and ability.get('ready') and obs.get('max_hp', 0) - obs.get('hp', 0) >= 5:
                return {'type': 'ability', 'ability': 'first_aid'}
        # Encounters can begin immediately after moving into an unknown room;
        # conserve enough health to survive a strong first response.
        if obs.get('potions', 0) and obs.get('hp', 0) <= 10:
            return {'type': 'potion'}
        npc = obs.get('npc')
        if npc and npc not in self.seen_npcs:
            self.seen_npcs.add(npc)
            return {'type': 'talk'}
        if npc:
            for topic in obs.get('topics') or []:
                topic_id = topic.get('id') if isinstance(topic, dict) else None
                if isinstance(topic_id, str) and topic_id.startswith('quest:') and (npc, topic_id) not in self.asked:
                    self.asked.add((npc, topic_id))
                    return {'type': 'ask', 'topic': topic_id}
        # Select the first actionable known objective, prioritizing the main
        # quest. An objective is actionable only when its disclosed dependencies
        # have already been witnessed; unknown dependencies cause exploration.
        blocked = self.dragon_rooms if 'рунический оберег' not in obs.get('inventory', []) else set()
        candidates = [(key, task) for key, task in self.tasks.items() if key not in self.done
                      and key not in self.stalled_targets and all(dep in self.done for dep in task['requires'])]
        candidates.sort(key=lambda pair: (0 if pair[0][0] == 'Сердце звезды' else 1, pair[0][1], pair[0][0]))
        for key, task in candidates:
            if task['room'] == room:
                if task['action'] == 'talk' and npc == task['target']:
                    return {'type': 'talk'}
                if task['action'] == 'search':
                    # A failed search should not monopolize the whole episode.
                    self.stalled_targets.add(key)
                    return {'type': 'search'}
                if task['action'] == 'defeat' and not obs.get('enemy'):
                    self.stalled_targets.add(key)
            else:
                direction = self._route(room, {task['room']}, blocked=blocked)
                if direction:
                    return {'type': 'move', 'direction': direction}
        direction = self._route(room, set(), frontier=True, blocked=blocked)
        if direction:
            return {'type': 'move', 'direction': direction}
        if self.exits.get(room):
            return {'type': 'move', 'direction': self.exits[room][0]}
        return {'type': 'search'}
