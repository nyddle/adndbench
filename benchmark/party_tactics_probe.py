"""Two *fixed* local diagnostics for party selection and combat tactics.

The seed is part of the replay interface, not a source of independent worlds.
Party success means the chosen role admits a winning path, found by BFS; it
does not say the model itself can execute that path. Tactical play fixes the
party and lets the model choose every battle action.
"""
from copy import deepcopy
from benchmark.party_combat import Battle, Party, ROLES, RULES, shortest_victory

VERSION = 'party-tactics-probe-0.1.0'
SYSTEM_PROMPT = ('Play the stated game. In the party diagnostic choose one ally '
                 'who makes victory possible with optimal later play. In the tactical '
                 'diagnostic win the battle by choosing one action per round. '
                 'All rules and enemy intentions are in the observation.')
ROLES_AVAILABLE = ('warden', 'medic', 'mage')


def make_party(roles):
    p = Party(gold=2, max_allies=2)
    for role in roles:
        assert p.recruit(role, present=[role])
    return p


def enemies(axis, level):
    if axis == 'party' and level == 'fixed':
        return [{'id':'armored','hp':12,'damage':3,'armor':2,'target_rule':'hero'}]
    if axis == 'tactics' and level in ('one','two','three'):
        return [{'id':f'foe{i}','hp':5,'damage':2,'armor':0,'target_rule':'hero'}
                for i in range({'one':1,'two':2,'three':3}[level])]
    raise ValueError('unsupported fixed diagnostic')


class Game:
    def __init__(self, seed, axis, level):
        self.seed=str(seed); self.axis=axis; self.level=level
        self.enemies=enemies(axis, level); self.turn=0; self.invalid_actions=0
        self.done=False; self.terminal_reason=None; self.selected=None
        self.battle=Battle(make_party(('medic','mage')),self.enemies) if axis=='tactics' else None

    def observe(self):
        out={'version':VERSION,'axis':self.axis,'level':self.level,'turn':self.turn,'done':self.done}
        if self.axis=='party':
            out.update(objective='Choose one ally for which a victory is possible with optimal later play.',
                       candidates=[{'id':role, **deepcopy(ROLES[role])} for role in ROLES_AVAILABLE],
                       hero=deepcopy(ROLES['hero']), enemies=deepcopy(self.enemies),
                       rules=RULES, max_rounds=12)
        else:
            out.update(objective='Win this battle.',battle=self.battle.observe())
        return out

    def step(self, action):
        if self.done: raise RuntimeError('game is over')
        self.turn+=1
        if self.axis=='party':
            if isinstance(action,dict) and set(action)=={'type','candidate'} and action.get('type')=='recruit' and action.get('candidate') in ROLES_AVAILABLE:
                self.selected=action['candidate']; p=Party(gold=1,max_allies=1)
                assert p.recruit(self.selected,present=[self.selected])
                solution=shortest_victory(Battle(p,self.enemies))
                if solution['status']=='unknown': raise RuntimeError('oracle incomplete')
                self.terminal_reason='completed' if solution['status']=='solved' else 'wrong_choice'
                self.done=True
            else: self.invalid_actions+=1
            if not self.done and self.turn>=4: self.done=True;self.terminal_reason='turn_limit'
        else:
            self.battle.step(action)
            if not self.battle.events[-1]['valid']: self.invalid_actions+=1
            if self.battle.status!='ongoing':
                self.done=True
                self.terminal_reason={'victory':'completed','defeat':'defeat','timeout':'combat_limit'}[self.battle.status]
        return self.observe()

    def result(self):
        result={'version':VERSION,'seed':self.seed,'axis':self.axis,'level':self.level,
                'terminal_reason':self.terminal_reason,'turns':self.turn,'invalid_actions':self.invalid_actions,
                'completed':self.terminal_reason=='completed'}
        if self.axis=='party': result['selected']=self.selected
        else:
            result.update(hero_hp=self.battle.party.members['hero']['hp'],
                          damage_dealt=sum(e['damage_dealt'] for e in self.battle.events),
                          healing=sum(e['healing'] for e in self.battle.events),
                          charges_used=sum(ROLES[m]['charges']-v['charges'] for m,v in self.battle.party.members.items()))
        return result


def allowed_actions(axis, obs):
    if axis=='party': return [{'type':'recruit','candidate':x} for x in ROLES_AVAILABLE]
    if axis!='tactics': raise ValueError('bad axis')
    battle=obs['battle']; actors=[p['id'] for p in battle['party']['members']]
    targets=actors+[e['id'] for e in battle['enemies']]
    return [{'type':kind,'actor':actor,'target':target} for kind in ('strike','blast','guard','heal')
            for actor in actors for target in targets]
