"""Standalone playable adventure integrating party recruitment and tactical combat.

This is a new opt-in scenario, separate from historical expedition results.
"""
from __future__ import annotations

import copy
from benchmark.party_combat import Battle, Party, RULES as COMBAT_RULES, VERSION as PARTY_VERSION

ENGINE_VERSION = 'party-adventure-0.1.1'
DEFAULT_MAX_TURNS = 60
SYSTEM_PROMPT = ('Complete the quest and return alive. The world is partially observed; '
                 'only the current room and available exits are shown. Recruit local candidates '
                 'with {"type":"recruit","candidate":"ID"} or move with '
                 '{"type":"move","direction":"north|south|east|west"}. '
                 'Inside an encounter follow battle.rules and use '
                 '{"type":"strike|guard|heal|blast","actor":"ID","target":"ID"}. '
                 'After the enemy is defeated use {"type":"search"} at the lair, then return home. '
                 'Each action consumes one turn, including invalid actions. No retreat from combat.')

ROOMS = {
    'home': {'name': 'Убежище', 'exits': {'north': 'crossroads'}, 'candidate': None},
    'crossroads': {'name': 'Перекрёсток', 'exits': {'south': 'home','north': 'outpost','east': 'grove','west': 'tower'}, 'candidate': None},
    'outpost': {'name': 'Застава', 'exits': {'south': 'crossroads','north': 'lair'}, 'candidate': 'warden'},
    'grove': {'name': 'Роща', 'exits': {'west': 'crossroads'}, 'candidate': 'medic'},
    'tower': {'name': 'Башня', 'exits': {'east': 'crossroads'}, 'candidate': 'mage'},
    'lair': {'name': 'Логово', 'exits': {'south': 'outpost'}, 'candidate': None},
}
ENCOUNTERS = {
    'easy': [{'id':'raider', 'hp': 6, 'damage': 2, 'armor': 0, 'target_rule':'hero'}],
    'medium': [{'id':'raider', 'hp': 8, 'damage': 3, 'armor': 0, 'target_rule':'hero'}],
    'hard': [{'id':'guard', 'hp': 8, 'damage': 2, 'armor': 1, 'target_rule':'hero'},
             {'id':'raider', 'hp': 6, 'damage': 2, 'armor': 0, 'target_rule':'hero'}],
}


class Game:
    def __init__(self, seed: str | int = 0, max_turns: int = DEFAULT_MAX_TURNS, *,
                 combat_difficulty: str = 'easy', max_allies: int = 2, gold: int = 2,
                 fixed_party: tuple[str, ...] | list[str] | None = None):
        if not isinstance(seed, (str, int)) or isinstance(seed, bool): raise ValueError('invalid seed')
        if type(max_turns) is not int or max_turns < 1: raise ValueError('invalid max_turns')
        if combat_difficulty not in ENCOUNTERS: raise ValueError('unknown combat difficulty')
        self.seed, self.max_turns, self.combat_difficulty = str(seed), max_turns, combat_difficulty
        self.party = Party(gold=gold, max_allies=max_allies)
        self.fixed_party = fixed_party is not None
        if fixed_party is not None:
            if not isinstance(fixed_party, (tuple, list)):
                raise ValueError('fixed_party must be a sequence')
            for role in fixed_party:
                if not self.party.recruit(role, present=[role]):
                    raise ValueError('invalid fixed_party')
        self.position, self.turn = 'home', 0
        self.visited = {'home'}
        self.battle = None
        self.encounter_won = False
        self.item_found = False
        self.done = False
        self.terminal_reason = None
        self.events = []
        self.message = 'Найдите реликвию в логове и вернитесь в убежище.'

    def observe(self) -> dict:
        room = ROOMS[self.position]
        present = [room['candidate']] if room['candidate'] and not self.fixed_party else []
        return {'engine_version': ENGINE_VERSION, 'room': room['name'],
                'exits': list(room['exits']), 'party': self.party.observe(present=present),
                'battle': self.battle.observe() if self.battle and self.battle.status == 'ongoing' else None,
                'scouting': copy.deepcopy(ENCOUNTERS[self.combat_difficulty]),
                'combat_rules': COMBAT_RULES,
                'inventory': ['реликвия'] if self.item_found else [], 'turn': self.turn,
                'max_turns': self.max_turns, 'message': self.message, 'done': self.done}

    def step(self, action: dict) -> dict:
        if self.done: raise RuntimeError('game is over')
        self.turn += 1
        valid = False
        if self.battle and self.battle.status == 'ongoing':
            self.battle.step(action)
            valid = self.battle.events[-1]['valid']
            self.message = 'Бой: действие выполнено.' if valid else 'Недопустимое действие; враги ответили.'
            if self.battle.status == 'victory':
                self.encounter_won = True
                self.message = 'Противники побеждены. Обыщите логово.'
            elif self.battle.status in ('defeat', 'timeout'):
                self.done, self.terminal_reason = True, ('death' if self.battle.status == 'defeat' else 'combat_limit')
        elif isinstance(action, dict) and set(action) == {'type', 'direction'} and action['type'] == 'move':
            target = ROOMS[self.position]['exits'].get(action['direction']) if isinstance(action['direction'], str) else None
            if target:
                valid = True
                self.position = target
                self.visited.add(target)
                self.message = 'Вы перешли в другую локацию.'
                if target == 'lair' and not self.encounter_won:
                    self.battle = Battle(self.party, copy.deepcopy(ENCOUNTERS[self.combat_difficulty]))
                    self.message = 'Вы встретили противников.'
            else:
                self.message = 'В этом направлении выхода нет.'
        elif isinstance(action, dict) and set(action) == {'type', 'candidate'} and action['type'] == 'recruit':
            candidate = ROOMS[self.position]['candidate']
            valid = bool(not self.fixed_party and candidate and self.party.recruit(action['candidate'], present=[candidate]))
            self.message = 'Союзник присоединился.' if valid else 'Невозможно нанять персонажа здесь.'
        elif isinstance(action, dict) and action == {'type':'search'} and self.position == 'lair' and self.encounter_won:
            valid = True
            self.item_found = True
            self.message = 'Вы нашли реликвию. Вернитесь в убежище.'
        else:
            self.message = 'Недопустимое действие.'
        if self.item_found and self.position == 'home':
            self.done, self.terminal_reason = True, 'completed'
        elif not self.done and self.turn >= self.max_turns:
            self.done, self.terminal_reason = True, 'turn_limit'
        self.events.append({'turn': self.turn, 'action': copy.deepcopy(action), 'valid': valid,
                            'room': self.position, 'terminal_reason': self.terminal_reason})
        return self.observe()

    def result(self) -> dict:
        return {'engine_version': ENGINE_VERSION, 'party_version': PARTY_VERSION,
                'combat_difficulty': self.combat_difficulty, 'turns': self.turn,
                'terminal_reason': self.terminal_reason, 'rooms_visited': len(self.visited),
                'fixed_party': self.fixed_party,
                'invalid_actions': sum(not e['valid'] for e in self.events),
                'recruited': self.party.recruited[:], 'party': self.party.snapshot(),
                'item_found': self.item_found, 'combat_rounds': self.battle.round if self.battle else 0,
                'combat_status': self.battle.status if self.battle else None}
