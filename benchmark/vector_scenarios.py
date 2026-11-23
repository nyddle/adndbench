"""Adapter for separate, versioned playable calibration scenarios."""
from __future__ import annotations

from itertools import product
from benchmark import memory_navigation, quest_chains, party_adventure, adventure_vectors, adventure_party

SCENARIOS = ('memory', 'navigation', 'quests', 'party', 'tactics',
             'adventure-memory', 'adventure-navigation', 'adventure-quests', 'adventure-full')
LEVELS = ('easy', 'medium', 'hard')


def create_game(axis: str, seed: str | int, level: str):
    if axis not in SCENARIOS or level not in LEVELS:
        raise ValueError('unknown axis or level')
    if axis in ('memory', 'navigation'):
        return memory_navigation.create_game(axis, seed, level)
    if axis == 'quests':
        return quest_chains.QuestChain(seed, {'easy': 'short', 'medium': 'medium', 'hard': 'long'}[level])
    if axis == 'adventure-full':
        # Demonstration of the combined game; changing multiple axes is not
        # a one-factor calibration.
        return adventure_party.Game(seed, memory=level, navigation=level, quests=level, combat_difficulty=level)
    if axis.startswith('adventure-'):
        setting = axis.removeprefix('adventure-')
        return adventure_vectors.Game(seed, **{setting: level})
    if axis == 'party':
        # Hold encounter fixed; vary capacity. This is an intervention on party
        # capacity, not a pure test of a model's recruitment choice.
        return party_adventure.Game(seed, combat_difficulty='medium', max_allies={'easy': 2, 'medium': 1, 'hard': 0}[level])
    # Tactics levels change enemy configurations; party capacity is constant.
    return party_adventure.Game(seed, combat_difficulty=level, fixed_party=('mage', 'medic'))


def system_prompt(axis: str) -> str:
    if axis in ('memory', 'navigation'):
        return memory_navigation.SYSTEM_PROMPTS[axis]
    if axis == 'adventure-full':
        return adventure_party.SYSTEM_PROMPT
    if axis.startswith('adventure-'):
        return adventure_vectors.SYSTEM_PROMPT
    if axis == 'quests':
        return ('Выполните цель, соблюдая зависимости задач; правила и доступные задачи в наблюдении. '
                'На каждом ходу верните один JSON-объект с полями type и target, без дополнительных полей.')
    if axis in ('party', 'tactics'):
        return party_adventure.SYSTEM_PROMPT
    raise ValueError('unknown axis')


def allowed_actions(axis: str, obs: dict) -> list[dict[str, str]]:
    """Enumerate only syntactically valid, public values; game judges legality."""
    if axis == 'memory':
        return ([{'type': 'move', 'direction': 'forward'}] +
                [{'type': 'answer', 'item': x} for x in memory_navigation.ITEMS])
    if axis == 'navigation':
        return [{'type': 'move', 'direction': d} for d in ('north', 'east', 'south', 'west')]
    if axis.startswith('adventure-'):
        actions = [{'type':'talk'}] + [{'type':'move','direction':d} for d in ('north','east','south','west')]
        actions += [{'type':'interact','target':t['id']} for t in obs.get('tasks', [])]
        actions += [{'type':'unlock','code':'-'.join(c)} for n in (1,2,3) for c in product(adventure_vectors.RUNES, repeat=n)]
        if axis == 'adventure-full':
            actions += [{'type':'recruit','candidate':r} for r in ('warden','medic','mage')]
            battle = obs.get('battle')
            if battle:
                members = [m['id'] for m in battle['party']['members']]
                enemies = [e['id'] for e in battle['enemies']]
                for actor in members:
                    for kind in ('strike', 'blast'):
                        actions.extend({'type':kind,'actor':actor,'target':t} for t in enemies)
                    for kind in ('guard', 'heal'):
                        actions.extend({'type':kind,'actor':actor,'target':t} for t in members)
        return actions
    if axis == 'quests':
        return [{'type': task['type'], 'target': task['target']} for task in obs['tasks']]
    if axis in ('party', 'tactics'):
        actions = ([{'type': 'move', 'direction': d} for d in ('north', 'east', 'south', 'west')] +
                   [{'type': 'recruit', 'candidate': candidate} for candidate in ('warden', 'medic', 'mage')] +
                   [{'type': 'search'}])
        battle = obs.get('battle')
        if battle:
            members = [m['id'] for m in battle['party']['members']]
            enemies = [e['id'] for e in battle['enemies']]
            for actor in members:
                for kind in ('strike', 'blast'):
                    actions.extend({'type': kind, 'actor': actor, 'target': target} for target in enemies)
                for kind in ('guard', 'heal'):
                    actions.extend({'type': kind, 'actor': actor, 'target': target} for target in members)
        return actions
    raise ValueError('unknown axis')
