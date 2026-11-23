"""Versioned, deterministic party and tactical encounter subsystem.

A host scenario owns movement and decides which candidates are present.  The
Party object is persistent between encounters; Battle mutates that same party.
This module is opt-in and does not change the historical expedition engine.
"""
from __future__ import annotations

import copy
from collections import deque
from typing import Any

VERSION = 'party-tactics-0.1.0'
ROLES = {
    'hero': {'hp': 12, 'cost': 0, 'charges': 0, 'ability': None},
    'warden': {'hp': 10, 'cost': 1, 'charges': 2, 'ability': 'guard'},
    'medic': {'hp': 8, 'cost': 1, 'charges': 2, 'ability': 'heal'},
    'mage': {'hp': 7, 'cost': 1, 'charges': 2, 'ability': 'blast'},
}
RULES = (
    'One living party member acts per round. strike deals 3 physical damage; armor '
    'reduces it by its stated amount, minimum 0. guard (warden, 1 charge) reduces '
    'each incoming hit to one living party member by 2 this round, minimum 0; '
    'the next strike deals 3 extra raw physical damage. '
    'heal (medic, 1 charge) restores up to 4 HP to a living injured member. '
    'blast (mage, 1 charge) deals 5 damage ignoring armor. '
    'Surviving enemies respond in listed order to their announced targets; '
    'a dead target is skipped. New intents are shown after the round. '
    'Invalid actions consume a round and surviving enemies still respond. '
    'The encounter is won when all enemies fall, lost if the hero falls, '
    'and timed out after max_rounds. Zero-HP allies cannot act or be healed.'
)


def _integer(value: Any, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


class Party:
    """Persistent party with explicit local recruitment and persistent charges.

    A host should pass candidate IDs actually present at the current room; it
    should never pass the private world-wide candidate list as a substitute.
    """
    def __init__(self, *, gold: int = 2, max_allies: int = 2):
        if not _integer(gold, 0, 20) or not _integer(max_allies, 0, 3):
            raise ValueError('invalid recruitment limits')
        self.gold, self.max_allies = gold, max_allies
        self.members = {'hero': self._new('hero')}
        self.recruited: list[str] = []

    @staticmethod
    def _new(role: str) -> dict:
        spec = ROLES[role]
        return {'id': role, 'role': role, 'hp': spec['hp'], 'max_hp': spec['hp'],
                'charges': spec['charges'], 'ability': spec['ability']}

    def recruit(self, candidate: str, *, present: list[str]) -> bool:
        """Recruit exactly one locally present named role; False is a no-op."""
        if (not isinstance(candidate, str) or candidate not in ROLES or candidate == 'hero'
                or candidate not in present or candidate in self.members
                or len(self.recruited) >= self.max_allies or self.gold < ROLES[candidate]['cost']
                or self.members['hero']['hp'] <= 0):
            return False
        self.gold -= ROLES[candidate]['cost']
        self.members[candidate] = self._new(candidate)
        self.recruited.append(candidate)
        return True

    def observe(self, *, present: list[str] = ()) -> dict:
        candidates = [{'id': name, **copy.deepcopy(ROLES[name])} for name in present
                      if name in ROLES and name != 'hero' and name not in self.members]
        return {'members': copy.deepcopy(list(self.members.values())), 'gold': self.gold,
                'max_allies': self.max_allies, 'candidates_here': candidates}

    def snapshot(self) -> dict:
        return {'gold': self.gold, 'max_allies': self.max_allies,
                'members': copy.deepcopy(self.members), 'recruited': self.recruited[:]}

    @classmethod
    def from_snapshot(cls, raw: dict) -> 'Party':
        if not isinstance(raw, dict) or set(raw) != {'gold', 'max_allies', 'members', 'recruited'}:
            raise ValueError('invalid party snapshot')
        p = cls(gold=raw['gold'], max_allies=raw['max_allies'])
        members, recruited = raw['members'], raw['recruited']
        if not isinstance(members, dict) or not isinstance(recruited, list):
            raise ValueError('invalid members')
        if (len(recruited) != len(set(recruited)) or any(x not in ('warden','medic','mage') for x in recruited)
                or len(recruited) > p.max_allies or set(members) != {'hero', *recruited}):
            raise ValueError('invalid recruited members')
        for role, member in members.items():
            if (not isinstance(member, dict) or set(member) != {'id','role','hp','max_hp','charges','ability'}
                    or member['id'] != role or member['role'] != role or member['max_hp'] != ROLES[role]['hp']
                    or member['ability'] != ROLES[role]['ability']
                    or not _integer(member['hp'], 0, ROLES[role]['hp'])
                    or not _integer(member['charges'], 0, ROLES[role]['charges'])):
                raise ValueError('invalid member state')
        p.members, p.recruited = copy.deepcopy(members), recruited[:]
        return p


class Battle:
    """A complete deterministic encounter; caller can persist the party afterwards."""
    def __init__(self, party: Party, enemies: list[dict], *, max_rounds: int = 12):
        if not isinstance(party, Party) or party.members['hero']['hp'] <= 0:
            raise ValueError('living party required')
        if not _integer(max_rounds, 1, 100) or not isinstance(enemies, list) or not 1 <= len(enemies) <= 3:
            raise ValueError('invalid encounter')
        self.enemies = []
        ids = set()
        for enemy in enemies:
            if (not isinstance(enemy, dict) or set(enemy) != {'id','hp','damage','armor','target_rule'}
                    or not isinstance(enemy['id'], str) or not enemy['id'] or enemy['id'] in ids
                    or not _integer(enemy['hp'], 1, 30) or not _integer(enemy['damage'], 0, 10)
                    or not _integer(enemy['armor'], 0, 2) or enemy['target_rule'] not in ('hero', 'weakest')):
                raise ValueError('invalid enemy')
            ids.add(enemy['id'])
            self.enemies.append({**enemy, 'max_hp': enemy['hp']})
        self.party, self.round, self.max_rounds = party, 0, max_rounds
        self.status = 'ongoing'
        self.braced = False
        self.events: list[dict] = []
        self._intents = self._next_intents()

    def _next_intents(self) -> list[dict]:
        live = [m for m in self.party.members.values() if m['hp'] > 0]
        result = []
        for e in self.enemies:
            if e['hp'] <= 0: continue
            target = 'hero' if e['target_rule'] == 'hero' else min(live, key=lambda m: (m['hp'], m['id']))['id']
            result.append({'enemy': e['id'], 'target': target, 'damage': e['damage']})
        return result

    def observe(self) -> dict:
        return {'version': VERSION, 'party': self.party.observe(), 'enemies': copy.deepcopy(self.enemies),
                'intents': copy.deepcopy(self._intents), 'round': self.round, 'max_rounds': self.max_rounds,
                'status': self.status, 'braced': self.braced, 'rules': RULES}

    def _valid(self, action: Any) -> bool:
        if not isinstance(action, dict) or set(action) != {'type', 'actor', 'target'}:
            return False
        kind, actor, target = action['type'], action['actor'], action['target']
        if not all(isinstance(x, str) for x in (kind, actor, target)): return False
        member = self.party.members.get(actor)
        if not member or member['hp'] <= 0: return False
        enemies = {e['id']: e for e in self.enemies}
        if kind in ('strike', 'blast'):
            return (target in enemies and enemies[target]['hp'] > 0 and
                    (kind == 'strike' or (member['ability'] == 'blast' and member['charges'] > 0)))
        recipient = self.party.members.get(target)
        if not recipient or recipient['hp'] <= 0: return False
        if kind == 'guard': return member['ability'] == 'guard' and member['charges'] > 0
        if kind == 'heal': return member['ability'] == 'heal' and member['charges'] > 0 and recipient['hp'] < recipient['max_hp']
        return False

    def step(self, action: dict) -> dict:
        if self.status != 'ongoing': raise RuntimeError('encounter is over')
        self.round += 1
        valid = self._valid(action)
        guard_target = None
        damage_dealt = 0
        healing = 0
        if valid:
            actor = self.party.members[action['actor']]
            kind, target = action['type'], action['target']
            if kind in ('strike','blast'):
                enemy = next(e for e in self.enemies if e['id'] == target)
                amount = max(0, 3 + (3 if self.braced else 0) - enemy['armor']) if kind == 'strike' else 5
                if kind == 'strike': self.braced = False
                damage_dealt = min(enemy['hp'], amount)
                enemy['hp'] -= damage_dealt
            elif kind == 'heal':
                recipient = self.party.members[target]
                healing = min(4, recipient['max_hp'] - recipient['hp'])
                recipient['hp'] += healing
            elif kind == 'guard':
                guard_target = target
                self.braced = True
            if kind != 'strike': actor['charges'] -= 1
        damage = []
        if all(e['hp'] == 0 for e in self.enemies):
            self.status = 'victory'
        else:
            for intent in self._intents:
                enemy = next(e for e in self.enemies if e['id'] == intent['enemy'])
                member = self.party.members[intent['target']]
                if enemy['hp'] <= 0 or member['hp'] <= 0: continue
                amount = max(0, intent['damage'] - (2 if guard_target == member['id'] else 0))
                amount = min(member['hp'], amount)
                member['hp'] -= amount
                damage.append({'enemy': enemy['id'], 'target': member['id'], 'damage': amount})
                if self.party.members['hero']['hp'] <= 0:
                    self.status = 'defeat'
                    break
            if self.status == 'ongoing' and self.round >= self.max_rounds: self.status = 'timeout'
        self.events.append({'round': self.round, 'action': copy.deepcopy(action), 'valid': valid,
                            'damage_dealt': damage_dealt, 'healing': healing, 'incoming': damage,
                            'status': self.status})
        self._intents = self._next_intents() if self.status == 'ongoing' else []
        return self.observe()

    def valid_actions(self) -> list[dict]:
        """List legal actions; public helper for policy implementations and oracle."""
        result = []
        for actor in self.party.members:
            for kind, targets in (('strike', [e['id'] for e in self.enemies]),
                                  ('blast', [e['id'] for e in self.enemies]),
                                  ('guard', list(self.party.members)), ('heal', list(self.party.members))):
                for target in targets:
                    action = {'type': kind, 'actor': actor, 'target': target}
                    if self._valid(action): result.append(action)
        return result


def _state_key(battle: Battle) -> tuple:
    return (battle.round, battle.status, battle.braced,
            tuple((m['id'], m['hp'], m['charges']) for m in battle.party.members.values()),
            tuple((e['id'], e['hp']) for e in battle.enemies))


def shortest_victory(battle: Battle, *, max_states: int = 100000) -> dict:
    """Breadth-first exact search over legal actions; bounded, no hidden policy.

    Reports exhaustive absence of victory only if the queue is fully explored;
    reaching max_states is explicitly 'unknown'. Does not mutate its argument.
    """
    if battle.status != 'ongoing' or not _integer(max_states, 1, 1000000):
        raise ValueError('ongoing battle and positive max_states required')
    queue = deque([(copy.deepcopy(battle), [])])
    seen = {_state_key(battle)}
    while queue:
        state, path = queue.popleft()
        for action in state.valid_actions():
            nxt = copy.deepcopy(state)
            nxt.step(action)
            result = path + [action]
            if nxt.status == 'victory':
                return {'status': 'solved', 'actions': result, 'states': len(seen)}
            if nxt.status != 'ongoing': continue
            key = _state_key(nxt)
            if key not in seen:
                if len(seen) >= max_states:
                    return {'status': 'unknown', 'actions': None, 'states': len(seen)}
                seen.add(key)
                queue.append((nxt, result))
    return {'status': 'unsolvable', 'actions': None, 'states': len(seen)}
