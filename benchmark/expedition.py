"""Configurable, partially observed expedition; historical scenarios stay frozen.

The engine is the only owner of mutable state. Difficulty modules generate
private specifications or deterministic effects; a player receives local
observations and facts explicitly obtained in conversation.
"""
from __future__ import annotations

from typing import Any
from benchmark.difficulty import maps, quests, combat, characters, npcs

ENGINE_VERSION = 'expedition-0.1.0'
DEFAULT_MAX_TURNS = 600
SYSTEM_PROMPT = """You are playing a turn-based fantasy adventure. Complete the required quests and survive.
Explore the lands, mountain, wizard's tower and dragon dungeon. Only the current location is
visible. Remember the map and what NPCs say. Each turn return exactly one JSON object.
Actions: {"type":"move","direction":"north|south|east|west|up|down"}, {"type":"talk"},
{"type":"ask","topic":"TOPIC_ID"}, {"type":"search"}, {"type":"attack"}, {"type":"defend"},
{"type":"potion"}, {"type":"rest"}, {"type":"ability","ability":"ABILITY_ID"}. The current
NPC's available topic IDs are in the observation. Talk accepts or advances quests; ask obtains
one fact about the selected topic. Directions are consistent within each region; up/down connect
regions. Speak with the elder in the starting refuge to begin. Some quests have dependencies.
Your class, available ability, energy, costs and cooldowns are shown in each observation.
Energy is finite and does not regenerate, including during rest.
Attack deals 3 physical damage, or 5 after defending. A potion heals up to 6 HP. Rest at the
starting refuge uses one ration and restores up to 8 HP. Retreat from a living enemy costs 3 HP.
Invalid actions consume a turn, and a living enemy responds even to an invalid action in combat. """ + combat.COMBAT_RULES


class Game:
    """A replayable episode with five separately controlled difficulty axes."""
    def __init__(self, seed: str | int, max_turns: int = DEFAULT_MAX_TURNS, *,
                 map_size: int = 6, quest_difficulty: str = 'easy',
                 combat_difficulty: str = 'easy', character_class: str = 'generalist',
                 npc_difficulty: str = 'easy', map_topology: str = 'mixed',
                 terrain_diversity: int = 2, enemy_count: int | None = None):
        if not isinstance(seed, (str, int)) or isinstance(seed, bool):
            raise ValueError('seed must be a string or integer')
        if not isinstance(max_turns, int) or isinstance(max_turns, bool) or max_turns < 1:
            raise ValueError('max_turns must be a positive integer')
        self.seed, self.max_turns = str(seed), max_turns
        self.config = {'map_size': map_size, 'quest_difficulty': quest_difficulty,
                       'combat_difficulty': combat_difficulty, 'character_class': character_class,
                       'npc_difficulty': npc_difficulty, 'map_topology': map_topology,
                       'terrain_diversity': terrain_diversity, 'enemy_count': enemy_count}
        self.component_versions = {'map': maps.MAP_VERSION, 'quests': quests.QUEST_VERSION,
                                   'combat': combat.COMBAT_VERSION,
                                   'character': characters.CHARACTER_VERSION,
                                   'npc': npcs.VERSION}
        self.world = maps.generate_map(self.seed, size=map_size, topology=map_topology,
                                       terrain_diversity=terrain_diversity)
        self.rooms = {r['id']: r for r in self.world['rooms']}
        self.plan = quests.generate_quests(self.seed, self.world, difficulty=quest_difficulty)
        self.quest_state = quests.initial_state()
        self.npc_knowledge = npcs.build_npc_knowledge(self.seed, self.world, self.plan,
                                                      difficulty=npc_difficulty)
        self.npc_at = {n['room_id']: n for n in self.plan['npcs']}
        self.items = {item['id']: item['name'] for item in self.plan['items']}
        self.objectives = {o['id']: o for q in self.plan['quests'] for o in q['objectives']}
        # Reserve all quest sites across profiles so changing quest difficulty
        # cannot silently change encounter placement on the same map and seed.
        reserved = set()
        for level in quests.DIFFICULTIES:
            plan = quests.generate_quests(self.seed, self.world, difficulty=level)
            reserved.update(n['room_id'] for n in plan['npcs'])
            reserved.update(o['room_id'] for q in plan['quests'] for o in q['objectives'])
        self.encounters = combat.generate_encounters(self.seed, self.world,
                            difficulty=combat_difficulty, extra_count=enemy_count,
                            reserved_room_ids=reserved)
        self.character = characters.create_character(character_class)
        self.position = self.world['sites']['elder']
        self.visited = {self.position}
        self.inventory: list[str] = []  # stable IDs, converted to names at observation
        self.hp = self.max_hp = 18
        self.potions, self.rations = 3, 2
        self.braced = False
        self.turn = 0
        self.done = False
        self.terminal_reason: str | None = None
        self.events: list[dict[str, Any]] = []
        self.message = ('Вы в убежище. Поговорите со старейшиной; изучайте открытые земли, '
                        'гору, башню и подземелье. У персонажей можно узнавать сведения по темам.')

    def _enemy(self) -> dict[str, Any] | None:
        enemy = self.encounters.get(self.position)
        return enemy if enemy and enemy['hp'] > 0 else None

    def observe(self) -> dict[str, Any]:
        room = self.rooms[self.position]
        npc = self.npc_at.get(self.position)
        enemy = self._enemy()
        visible_enemy = None if enemy is None else {
            'name': enemy['name'], 'hp': enemy['hp'],
            'intent': combat.intent(enemy['kind'], enemy['phase'], ward='ward' in self.inventory,
                                    difficulty=enemy['difficulty']),
        }
        return {'room': room['name'], 'zone': room['zone'], 'terrain': room['terrain'],
                'exits': [d for d in ('north','south','east','west','up','down') if d in room['exits']],
                'npc': npc['name'] if npc else None,
                'topics': npcs.get_topics(self.npc_knowledge, npc['id']) if npc else [],
                'enemy': visible_enemy, 'hp': self.hp, 'max_hp': self.max_hp,
                'inventory': [self.items[i] for i in self.inventory],
                'potions': self.potions, 'rations': self.rations,
                'character': characters.describe_character(self.character),
                'turn': self.turn, 'max_turns': self.max_turns,
                'message': self.message, 'done': self.done}

    def _hurt(self, amount: int) -> int:
        taken = min(self.hp, amount)
        self.hp -= taken
        return taken

    def _response(self, enemy: dict[str, Any], *, defending: bool = False) -> int:
        if enemy['hp'] <= 0:
            return 0
        damage = combat.incoming(enemy['kind'], enemy['phase'], ward='ward' in self.inventory,
                                 defending=defending, difficulty=enemy['difficulty'])
        enemy['phase'] += 1
        return self._hurt(damage)

    def _advance(self, event_type: str, target_id: str) -> tuple[list[str], list[dict[str, Any]]]:
        before = set(self.quest_state['completed_objectives'])
        event = {'event': event_type, 'target_id': target_id, 'room_id': self.position}
        self.quest_state, notifications = quests.advance(self.plan, self.quest_state, event)
        newly = [oid for oid in self.quest_state['completed_objectives'] if oid not in before]
        if 'main_ward' in newly and 'ward' not in self.inventory:
            self.inventory.append('ward')
        for note in notifications:
            q = next(q for q in self.plan['quests'] if q['id'] == note['quest_id'])
            # The quest's collected objects are delivered once upon completion.
            for obj in q['objectives']:
                if obj['event'] == 'search' and obj['target_id'] in self.inventory:
                    self.inventory.remove(obj['target_id'])
            self.potions += note['rewards']['potions']
            for item_id in note['rewards']['items']:
                if item_id not in self.inventory:
                    self.inventory.append(item_id)
        return newly, notifications

    def _hit(self, enemy: dict[str, Any], damage: int, damage_type: str) -> tuple[int, int, list[str]]:
        dealt = combat.apply_hit(enemy['kind'], enemy['phase'], damage, damage_type=damage_type,
                                 difficulty=enemy['difficulty'])
        dealt = min(enemy['hp'], dealt)
        enemy['hp'] -= dealt
        newly = []
        if enemy['hp'] <= 0 and enemy['kind'] == 'dragon':
            newly, _ = self._advance('defeat', 'dragon')
        incoming = self._response(enemy)
        return dealt, incoming, newly

    def step(self, action: dict[str, Any]) -> dict[str, Any]:
        if self.done:
            raise RuntimeError('game is over')
        self.turn += 1
        before = self.position
        enemy = self._enemy()
        npc = self.npc_at.get(self.position)
        kind = action.get('type') if isinstance(action, dict) else None
        event: dict[str, Any] = {'turn': self.turn, 'action': action, 'from_room': before}
        valid, damage, used_ability = True, 0, None
        if kind == 'move':
            direction = action.get('direction')
            exits = self.rooms[self.position]['exits']
            if not isinstance(direction, str) or direction not in exits:
                valid, self.message = False, 'Туда нельзя пройти.'
            else:
                if enemy:
                    damage = self._hurt(3)
                self.position = exits[direction]
                self.visited.add(self.position)
                self.braced = False
                self.message = 'Вы перешли в другую локацию.'
                if damage:
                    self.message += f' При отступлении вы потеряли {damage} здоровья.'
        elif enemy and kind in ('talk', 'ask', 'search', 'rest'):
            valid, self.message = False, 'Противник мешает действию; сражайтесь или отступите.'
        elif kind == 'talk':
            if not npc:
                valid, self.message = False, 'Здесь не с кем говорить.'
            else:
                had_ward = 'ward' in self.inventory
                newly, completed = self._advance('talk', npc['id'])
                messages = []
                # On easy/medium the wizard's visit is a sticky quest fact.
                # Give the ward at the encounter itself even if the player
                # has not yet accepted the elder's quest, rather than making
                # it appear remotely on a later conversation with the elder.
                if (npc['id'] == 'wizard' and self.config['quest_difficulty'] != 'hard'
                        and 'ward' not in self.inventory):
                    self.inventory.append('ward')
                    messages.append('Маг вручает рунический оберег: он снижает урон дыхания дракона и снимает печать.')
                for oid in newly:
                    obj = self.objectives[oid]
                    if oid.endswith('_accept'):
                        q = next(q for q in self.plan['quests'] if obj in q['objectives'])
                        text = q['briefing'] if self.config['npc_difficulty'] == 'easy' else (
                            f"Получено поручение «{q['title']}». Спросите жителей о его шагах.")
                        messages.append(f"{npc['name']}: {text}")
                    elif oid == 'main_ward':
                        messages.append('Засчитан ранее полученный оберег.' if had_ward else
                                        'Получен рунический оберег: он снижает урон дыхания дракона и снимает печать.')
                for note in completed:
                    q = next(q for q in self.plan['quests'] if q['id'] == note['quest_id'])
                    messages.append(f"Поручение «{q['title']}» выполнено. Награда: {note['rewards']['potions']} зелий.")
                self.message = ' '.join(messages) or f"{npc['name']}: выберите тему вопроса или выполните предварительные условия."
                if newly:
                    event['objectives'] = newly
        elif kind == 'ask':
            if not npc:
                valid, self.message = False, 'Здесь не с кем говорить.'
            else:
                answer = npcs.dialogue(self.npc_knowledge, npc['id'], action.get('topic'))
                valid, self.message = answer['valid'], answer['message']
        elif kind == 'search':
            matches = [o for o in self.objectives.values() if o['event'] == 'search' and o['room_id'] == self.position]
            eligible = []
            for obj in matches:
                candidate = {'event': 'search', 'target_id': obj['target_id'], 'room_id': self.position}
                if obj['id'] in quests.eligible_objectives(self.plan, self.quest_state, candidate):
                    eligible.append(obj)
            if eligible:
                obj = eligible[0]
                if obj['target_id'] not in self.inventory:
                    self.inventory.append(obj['target_id'])
                newly, _ = self._advance('search', obj['target_id'])
                event['objectives'] = newly
                self.message = f"Вы нашли предмет: {self.items[obj['target_id']]}."
            else:
                self.message = 'Вы не нашли ничего полезного; возможно, предварительные условия не выполнены.'
        elif kind in ('attack', 'defend'):
            if not enemy:
                valid, self.message = False, 'Здесь нет противника.'
            elif kind == 'attack':
                raw = 5 if self.braced else 3
                self.braced = False
                dealt, damage, newly = self._hit(enemy, raw, 'physical')
                event.update(damage_dealt=dealt, objectives=newly)
                self.message = f'Вы нанесли {dealt} урона. Противник ответил: −{damage} здоровья.'
                if enemy['hp'] == 0:
                    self.message += ' Противник побеждён.'
            else:
                self.braced = True
                damage = self._response(enemy, defending=True)
                self.message = f'Вы защищаетесь: потеряли {damage} здоровья; следующая обычная атака сильнее.'
        elif kind == 'ability':
            new_state, effect = characters.use_ability(self.character, action.get('ability'),
                                in_combat=bool(enemy), hp=self.hp, max_hp=self.max_hp)
            valid, self.message = effect['valid'], effect['message']
            if valid:
                self.character = new_state
                used_ability = effect['ability_id']
                if 'heal' in effect:
                    self.hp += effect['heal']
                    self.message += f" Восстановлено {effect['heal']} здоровья."
                if effect.get('reveal') == 'adjacent_rooms':
                    visible = {direction: self.rooms[target]['name']
                               for direction, target in self.rooms[self.position]['exits'].items()}
                    self.message += ' Соседние локации: ' + ', '.join(f'{k}: {v}' for k, v in visible.items()) + '.'
                if 'damage' in effect and enemy:
                    dealt, damage, newly = self._hit(enemy, effect['damage'], effect['damage_type'])
                    event.update(damage_dealt=dealt, objectives=newly)
                    self.message += f' Урон врагу: {dealt}; ответ: {damage}.'
                    if enemy['hp'] == 0:
                        self.message += ' Противник побеждён.'
                elif enemy and effect.get('opponent_response'):
                    damage = self._response(enemy)
                    self.message += f' Противник ответил: −{damage} здоровья.'
        elif kind == 'potion':
            if self.potions <= 0 or self.hp == self.max_hp:
                valid, self.message = False, 'Зелье сейчас использовать нельзя.'
            else:
                self.potions -= 1
                healed = min(6, self.max_hp - self.hp)
                self.hp += healed
                damage = self._response(enemy) if enemy else 0
                self.message = f'Зелье восстановило {healed} здоровья; ответ противника: {damage}.'
        elif kind == 'rest':
            if self.position != self.world['sites']['elder'] or self.rations <= 0 or self.hp == self.max_hp:
                valid, self.message = False, 'Отдых доступен только в убежище при наличии припасов и ран.'
            else:
                self.rations -= 1
                healed = min(8, self.max_hp - self.hp)
                self.hp += healed
                self.message = f'Вы отдохнули и восстановили {healed} здоровья.'
        else:
            valid, self.message = False, 'Неизвестное действие.'
        # Time still passes in combat on invalid actions. Otherwise a player
        # could wait out cooldowns indefinitely without taking the telegraphed
        # enemy response, bypassing the tactical trade-off.
        if not valid and enemy:
            damage = self._response(enemy)
            self.message += f' Противник ответил: −{damage} здоровья.'
        self.character = characters.advance_turn(self.character, used_ability_id=used_ability)
        event.update(valid=valid, to_room=self.position, damage_taken=damage, hp=self.hp)
        self.events.append(event)
        if self.hp <= 0:
            self.done, self.terminal_reason = True, 'death'
        elif quests.required_complete(self.plan, self.quest_state):
            self.done, self.terminal_reason = True, 'completed'
        elif self.turn >= self.max_turns:
            self.done, self.terminal_reason = True, 'turn_limit'
        return self.observe()

    def result(self) -> dict[str, Any]:
        completed = set(self.quest_state['completed_quests'])
        side = [q for q in self.plan['quests'] if not q['required']]
        return {'engine_version': ENGINE_VERSION, 'seed': self.seed, 'config': dict(self.config),
                'component_versions': dict(self.component_versions),
                'turns': self.turn, 'terminal_reason': self.terminal_reason,
                'additional_encounters_generated': len(self.encounters) - 1,
                'quests_completed': len(completed), 'quests_total': len(self.plan['quests']),
                'main_quest_completed': quests.required_complete(self.plan, self.quest_state),
                'side_quests_completed': sum(q['id'] in completed for q in side),
                'side_quests_total': len(side),
                'moves': sum(e['valid'] and e['from_room'] != e['to_room'] for e in self.events),
                'invalid_actions': sum(not e['valid'] for e in self.events),
                'rooms_visited': len(self.visited), 'rooms_total': len(self.rooms),
                'attacks': sum(e['valid'] and isinstance(e['action'], dict) and e['action'].get('type') == 'attack' for e in self.events),
                'damage_taken': sum(e['damage_taken'] for e in self.events),
                'potions_used': sum(e['valid'] and isinstance(e['action'], dict) and e['action'].get('type') == 'potion' for e in self.events),
                'deaths': int(self.terminal_reason == 'death'), 'events': self.events.copy()}
