#!/usr/bin/env python3
"""Deterministic small local checks; no model requests and no hidden datasets."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark.party_combat import Party, Battle, shortest_victory, VERSION


def party(roles):
    p = Party(gold=2, max_allies=2)
    for role in roles:
        assert p.recruit(role, present=[role])
    return p


def play(roles, enemies, policy):
    p = party(roles); b = Battle(p, enemies)
    oracle = shortest_victory(b)
    if oracle['status'] == 'solved':
        replay = Battle(party(roles), enemies)
        for action in oracle['actions']: replay.step(action)
        assert replay.status == 'victory'
    while b.status == 'ongoing':
        target = min((e for e in b.enemies if e['hp'] > 0), key=lambda e: (e['hp'],e['id']))
        medic, mage = p.members.get('medic'), p.members.get('mage')
        warden = p.members.get('warden')
        if policy == 'roles' and medic and medic['hp'] > 0 and medic['charges'] and p.members['hero']['hp'] <= 5:
            action = {'type':'heal','actor':'medic','target':'hero'}
        elif policy == 'roles' and mage and mage['hp'] > 0 and mage['charges']:
            action = {'type':'blast','actor':'mage','target':target['id']}
        elif policy == 'roles' and warden and warden['hp'] > 0 and warden['charges'] and not b.braced:
            action = {'type':'guard','actor':'warden','target':'hero'}
        else:
            action = {'type':'strike','actor':'hero','target':target['id']}
        b.step(action)
    return {'policy': policy, 'outcome': b.status, 'rounds': b.round,
            'hero_hp': p.members['hero']['hp'],
            'charges_spent': sum((2 - m['charges']) for m in p.members.values() if m['ability']),
            'oracle_status': oracle['status'],
            'oracle_shortest_rounds': len(oracle['actions']) if oracle['actions'] is not None else None}


def main():
    tactics=[]
    for count in (1,2,3):
        enemies = [{'id':f'foe{i}', 'hp':5, 'damage':2, 'armor':0, 'target_rule':'hero'} for i in range(count)]
        for policy in ('strike_only','roles'):
            tactics.append({'enemies': count, **play(('medic','mage'), enemies, policy)})
    recruitment=[]
    fixed = [{'id':'armored', 'hp':12, 'damage':3, 'armor':2, 'target_rule':'hero'}]
    for role in ('warden','medic','mage'):
        for policy in ('strike_only','roles'):
            recruitment.append({'role':role, **play((role,), fixed, policy)})
    print(json.dumps({'protocol':VERSION, 'tactics_fixed_party':tactics, 'party_fixed_encounter':recruitment,
        'note':'One handcrafted encounter per condition; no independent worlds or LLM. '
               'BFS uses the same engine, and no victory is inferred when capped. '
               'Levels and role availability are separate from game-mode defaults.'},ensure_ascii=False,indent=2))
if __name__ == '__main__': main()
