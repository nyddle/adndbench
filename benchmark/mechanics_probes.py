"""Probes about numeric combat mechanics, derived only from observed events.

Each fact is taken from messages the agent actually saw; nothing is read from
the system prompt or hidden state. A question is emitted only when every
observed instance of the fact has the same value, so the answer is always
unambiguous. These probes are meaningful under a prompt that omits the combat
numbers (hidden-rules protocol); with the full prompt they measure reading,
not inference.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from benchmark.probes import public_probe

__all__ = ['build_mechanics_probes', 'public_probe', 'check_answer']

_ATTACK = re.compile(r'Вы нанесли (\d+) урона')
_RESPONSE = re.compile(r'Противник ответил: −(\d+)')
_RETREAT = re.compile(r'При отступлении вы потеряли (\d+)')
_DEFEND = re.compile(r'защищаетесь: потеряли (\d+) здоров')

_FACTS = {
    'attack_plain': 'Какой урон наносит ваша обычная атака без предварительной защиты?',
    'attack_boosted': 'Какой урон наносит ваша атака сразу после защиты?',
    'enemy_response': 'Сколько здоровья вы теряете, когда противник переживает вашу атаку?',
    'retreat_cost': 'Сколько здоровья стоит отступление, пока противник жив?',
    'defend_cost': 'Сколько здоровья стоит вам сама защита?',
}
_INT = re.compile(r'\d+')


def build_mechanics_probes(trace: Sequence[Mapping[str, Any]],
                           final_observation: Mapping[str, Any]) -> list[dict[str, str]]:
    """One question per consistent numeric fact observed in the trace."""
    seen: dict[str, set[int]] = {key: set() for key in _FACTS}
    previous_kind = None
    for index, turn in enumerate(trace):
        if not isinstance(turn, Mapping):
            continue
        action = turn.get('action')
        kind = action.get('type') if isinstance(action, Mapping) else None
        following = (trace[index + 1].get('observation')
                     if index + 1 < len(trace) else final_observation)
        message = following.get('message') if isinstance(following, Mapping) else None
        if isinstance(message, str):
            if kind == 'attack':
                key = 'attack_boosted' if previous_kind == 'defend' else 'attack_plain'
                for value in _ATTACK.findall(message):
                    seen[key].add(int(value))
            for value in _RESPONSE.findall(message):
                # A zero response means the enemy died or could not respond;
                # it is not the "survived attack" fact.
                if int(value) > 0:
                    seen['enemy_response'].add(int(value))
            for value in _RETREAT.findall(message):
                seen['retreat_cost'].add(int(value))
            for value in _DEFEND.findall(message):
                seen['defend_cost'].add(int(value))
        previous_kind = kind
    probes = []
    for key, question in _FACTS.items():
        values = seen[key]
        if len(values) != 1:
            # Not observed, or observed with conflicting values (e.g. a dragon
            # alternating breath and claws): no unambiguous question to ask.
            continue
        answer = values.pop()
        probes.append({'id': f'mechanics_{key}', 'capability': 'mechanics_inference',
                       'question': question + ' Ответьте одним числом.', 'answer': str(answer)})
    return probes


def check_answer(probe: Mapping[str, str], answer: Any) -> bool:
    """The response must contain exactly the expected number and no other."""
    if not isinstance(answer, str):
        return False
    return set(_INT.findall(answer)) == {probe['answer']}
