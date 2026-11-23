"""Opt-in integrated adventure with recruitment and one tactical encounter.

When both extensions are disabled all observations, steps, and results are
identical to the standalone adventure. This wrapper never modifies that engine.
"""
from __future__ import annotations

import copy
from collections import deque
import hashlib
from pathlib import Path
from benchmark import adventure_vectors as base
from benchmark.fixed_probes import _Stream
from benchmark.party_combat import Party, Battle, RULES, VERSION as PARTY_VERSION
from benchmark.party_adventure import ENCOUNTERS

VERSION = 'adventure-party-0.1.0'
def system_prompt(party_enabled=True, combat_enabled=True):
    prompt = base.SYSTEM_PROMPT
    if party_enabled:
        prompt += (' Можно встретить союзников и нанять их действием '
                   '{"type":"recruit","candidate":"ID"}, только если кандидат находится здесь.')
    if combat_enabled:
        prompt += (' При входе в комнату замка начинается бой; до победы уйти нельзя. '
                   'На каждый раунд выберите действие {"type":"strike|guard|heal|blast",'
                   '"actor":"ID","target":"ID"}; правила и намерения противников отображаются '
                   'в наблюдении. Гибель героя заканчивает игру. После победы откройте замок.')
    return prompt


SYSTEM_PROMPT = system_prompt()


def source_fingerprint():
    h = hashlib.sha256()
    for filename in ('adventure_party.py','adventure_vectors.py','fixed_probes.py','party_combat.py','party_adventure.py'):
        p = Path(__file__).with_name(filename)
        h.update(p.name.encode() + b'\0' + p.read_bytes() + b'\0')
    return h.hexdigest()


class Game:
    def __init__(self, seed: str | int, *, memory='easy', navigation='easy', quests='easy',
                 max_turns=200, party_enabled=True, combat_enabled=True,
                 combat_difficulty='easy', max_allies=2, gold=2):
        if type(party_enabled) is not bool or type(combat_enabled) is not bool:
            raise ValueError('extension flags must be booleans')
        if combat_difficulty not in ENCOUNTERS:
            raise ValueError('unknown combat difficulty')
        self.game = base.Game(seed, memory=memory, navigation=navigation, quests=quests, max_turns=max_turns)
        self.party_enabled, self.combat_enabled = party_enabled, combat_enabled
        self.combat_difficulty = combat_difficulty
        self.party = Party(gold=gold, max_allies=max_allies if party_enabled else 0) if party_enabled or combat_enabled else None
        self.battle = None
        self.encounter_won = False
        self.encounter_started = False
        # This independent stream cannot alter existing map, tasks, or memory.
        rng = _Stream(str(seed), f'{VERSION}:recruits')
        # Assign using the hard map with lock removed, so every companion is
        # accessible before combat at every navigation level (whose edge sets
        # are supersets of hard). Rooms may contain multiple candidates.
        hard_edges, _, hard_home, _, hard_lock = base._build_world(str(seed), 'hard')
        reachable, queue = {hard_home}, deque([hard_home])
        while queue:
            room = queue.popleft()
            for nxt in hard_edges[room].values():
                if nxt != hard_lock and nxt not in reachable:
                    reachable.add(nxt); queue.append(nxt)
        cells = sorted(reachable - {hard_home})
        if len(cells) < 3: cells.append(hard_home)
        rng.shuffle(cells)
        self.candidates = {}
        if party_enabled:
            for i, role in enumerate(('warden','medic','mage')):
                self.candidates.setdefault(cells[i % len(cells)], []).append(role)

    @property
    def done(self): return self.game.done

    @property
    def turn(self): return self.game.turn

    @property
    def max_turns(self): return self.game.max_turns

    def _finish_external_action(self):
        if not self.game.done and self.game.turn >= self.game.max_turns:
            self.game.done, self.game.terminal_reason = True, 'turn_limit'

    def observe(self):
        obs = self.game.observe()
        if not self.party_enabled and not self.combat_enabled:
            return obs
        present = self.candidates.get(self.game.position, [])
        obs.update(extension_version=VERSION, party_version=PARTY_VERSION,
                   party=self.party.observe(present=present),
                   battle=self.battle.observe() if self.battle and self.battle.status == 'ongoing' else None,
                   encounter={'enabled':self.combat_enabled, 'started':self.encounter_started,
                              'won':self.encounter_won,
                              'status':self.battle.status if self.battle else None})
        if self.combat_enabled:
            obs.update(combat_rules=RULES, scouting=copy.deepcopy(ENCOUNTERS[self.combat_difficulty]))
        return obs

    def step(self, action):
        if self.game.done: raise RuntimeError('episode is over')
        if not self.party_enabled and not self.combat_enabled:
            return self.game.step(action)
        if self.battle and self.battle.status == 'ongoing':
            self.game.turn += 1
            self.battle.step(action)
            valid = self.battle.events[-1]['valid']
            if not valid: self.game.invalid_actions += 1
            self.game.notice = {'text':'Действие в бою выполнено.' if valid else 'Недопустимое действие; враги ответили.'}
            if self.battle.status == 'victory':
                self.encounter_won = True
                self.game.notice = {'text':'Противники побеждены.'}
            elif self.battle.status in ('defeat','timeout'):
                self.game.done = True
                self.game.terminal_reason = 'death' if self.battle.status == 'defeat' else 'combat_limit'
            self._finish_external_action()
            return self.observe()
        if isinstance(action,dict) and set(action) == {'type','candidate'} and action.get('type') == 'recruit':
            self.game.turn += 1
            present = self.candidates.get(self.game.position, [])
            valid = bool(self.party_enabled and self.party.recruit(action['candidate'], present=present))
            if not valid: self.game.invalid_actions += 1
            self.game.notice = {'text':'Союзник присоединился.' if valid else 'Невозможно нанять персонажа здесь.'}
            self._finish_external_action()
            return self.observe()
        # Ensure lock cannot be opened without winning the encounter, including
        # nonstandard action sequences and future changes to the base engine.
        if self.combat_enabled and not self.encounter_won and isinstance(action,dict) and action.get('type') == 'unlock':
            self.game.turn += 1; self.game.invalid_actions += 1
            self.game.notice = {'text':'Замок недоступен до победы в бою.'}
            self._finish_external_action()
            return self.observe()
        previous_position = self.game.position
        self.game.step(action)
        if (self.combat_enabled and not self.game.done and not self.encounter_started
            and previous_position != self.game.position and self.game.position == self.game.lock):
            self.battle = Battle(self.party, copy.deepcopy(ENCOUNTERS[self.combat_difficulty]))
            self.encounter_started = True
            self.game.notice = {'text':'У замка появились противники; начался бой.'}
        return self.observe()

    def result(self):
        result = self.game.result()
        if not self.party_enabled and not self.combat_enabled:
            return result
        result.update(extension_version=VERSION, party_version=PARTY_VERSION,
                      party_enabled=self.party_enabled, combat_enabled=self.combat_enabled,
                      combat_difficulty=self.combat_difficulty if self.combat_enabled else None,
                      party=self.party.snapshot(), combat_status=self.battle.status if self.battle else None,
                      combat_rounds=self.battle.round if self.battle else 0,
                      combat_victory=self.encounter_won)
        return result
