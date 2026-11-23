"""Map-free, deterministic multi-step quest scenario for development calibration.

Player sees all instructions and progress; this isolates prerequisite planning
from navigation, combat, and memory. Seeds and score/oracle stay evaluator-only.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Any

from benchmark.fixed_probes import _Stream

VERSION = 'quest-chains-0.1.0'
LEVELS = {'short': 3, 'medium': 5, 'long': 7}
# Distinct action targets and descriptions; assigned randomly to graph nodes.
CAST = (
    ('talk', 'смотритель', 'Поговорить со смотрителем'),
    ('search', 'лунный камень', 'Найти лунный камень'),
    ('talk', 'кузнец', 'Поговорить с кузнецом'),
    ('search', 'руническая печать', 'Найти руническую печать'),
    ('talk', 'целительница', 'Поговорить с целительницей'),
    ('search', 'старый ключ', 'Найти старый ключ'),
    ('talk', 'архивариус', 'Поговорить с архивариусом'),
    ('search', 'серебряная нить', 'Найти серебряную нить'),
    ('talk', 'следопыт', 'Поговорить со следопытом'),
    ('search', 'янтарный свиток', 'Найти янтарный свиток'),
    ('talk', 'маг', 'Поговорить с магом'),
    ('search', 'хрустальный компас', 'Найти хрустальный компас'),
)


def source_fingerprint() -> str:
    d = hashlib.sha256()
    for path in (Path(__file__), Path(__file__).with_name('fixed_probes.py')):
        d.update(path.name.encode() + b'\0' + path.read_bytes() + b'\0')
    return d.hexdigest()


def generate_plan(seed: str | int, level: str) -> dict[str, Any]:
    """Evaluator plan; no seed is included in returned structure.

    Same seed produces the same task graph at each level; the first 7-n
    chain tasks are already completed, so the remaining depth varies while
    the task menu, goal, side branch and two distractors remain fixed. IDs
    and task presentation order are independently shuffled.
    """
    if not isinstance(seed, (str, int)) or isinstance(seed, bool):
        raise ValueError('seed must be a string or integer')
    if level not in LEVELS:
        raise ValueError('unknown level')
    rng = _Stream(str(seed), VERSION)
    cast = list(CAST)
    rng.shuffle(cast)
    ids = [f'Q{i:02}' for i in range(1, 13)]
    rng.shuffle(ids)
    # Stable roles per seed: 0..6 chain, 7 goal, 8..9 side chain,
    # 10..11 independent distractors. Only completed progress changes.
    n = LEVELS[level]
    specs = []
    for i, (action_type, target, description) in enumerate(cast):
        if i < 7:
            requires = [] if i == 0 else [ids[i - 1]]
        elif i == 7:
            requires = [ids[6], ids[9]]
        elif i == 9:
            requires = [ids[8]]
        else:
            requires = []
        specs.append({'id': ids[i], 'type': action_type, 'target': target,
                      'description': description, 'requires': requires})
    rng.shuffle(specs)
    return {'version': VERSION, 'level': level, 'goal': ids[7], 'tasks': specs,
            'initial_done': sorted(ids[:7 - n])}


def _by_id(plan):
    return {task['id']: task for task in plan['tasks']}


def eligible(plan: dict, done: frozenset[str]) -> list[dict]:
    return [task for task in plan['tasks']
            if task['id'] not in done and set(task['requires']) <= done]


def oracle(plan: dict) -> list[dict]:
    """Find a shortest goal-reaching sequence by BFS, not by generator roles."""
    tasks = _by_id(plan)
    if len(tasks) != len(plan['tasks']) or plan['goal'] not in tasks:
        raise ValueError('invalid task IDs or goal')
    initial = frozenset(plan['initial_done'])
    if not initial <= tasks.keys():
        raise ValueError('unknown initially completed task')
    queue = deque([(initial, [])])
    seen = {initial}
    while queue:
        done, path = queue.popleft()
        if plan['goal'] in done:
            return path
        for t in eligible(plan, done):
            next_done = done | {t['id']}
            if next_done not in seen:
                seen.add(next_done)
                queue.append((next_done, path + [{'type': t['type'], 'target': t['target']}]))
    raise ValueError('goal unreachable')


class QuestChain:
    """A standalone deterministic action environment, not a text-only probe."""
    def __init__(self, seed: str | int, level: str, max_turns: int = 24):
        if type(max_turns) is not int or max_turns < 1:
            raise ValueError('max_turns must be a positive integer')
        self.plan = generate_plan(seed, level)
        self.max_turns = max_turns
        self.turns = 0
        self.done: set[str] = set(self.plan['initial_done'])
        self.invalid_actions = 0
        self.last_event = 'Начало поручения.'
        self._optimum = len(oracle(self.plan))
        self.terminal_reason: str | None = None

    def observe(self) -> dict:
        # Full graph and completion state are visible intentionally: this
        # scenario measures planning, not memory or exploring the environment.
        return {'version': VERSION, 'goal': self.plan['goal'],
                'tasks': deepcopy(self.plan['tasks']),
                'completed': sorted(self.done), 'turn': self.turns,
                'turns_remaining': max(0, self.max_turns - self.turns),
                'last_event': self.last_event, 'terminal_reason': self.terminal_reason,
                'rules': ('Чтобы выполнить поручение, передайте JSON с полями type и target из списка задач. '
                          'Его prerequisites перечислены в requires; все они должны быть завершены заранее. '
                          'Цель — выполнить задачу goal за минимальное число ходов. '
                          'Неверное, повторное или преждевременное действие тратит ход. '
                          'Карта, бои и ограничения ресурсов отсутствуют.')}

    def step(self, action: Any) -> dict:
        if self.terminal_reason is not None:
            raise ValueError('episode is already over')
        self.turns += 1
        match = None
        if (isinstance(action, dict) and set(action) == {'type', 'target'}
                and isinstance(action['type'], str) and isinstance(action['target'], str)):
            match = next((x for x in self.plan['tasks']
                          if x['type'] == action['type'] and x['target'] == action['target']), None)
        if match and match['id'] not in self.done and set(match['requires']) <= self.done:
            self.done.add(match['id'])
            self.last_event = f"Выполнено: {match['id']}."
        else:
            self.invalid_actions += 1
            self.last_event = 'Действие не выполнено: оно неизвестно, повторено или условия не выполнены.'
        if self.plan['goal'] in self.done:
            self.terminal_reason = 'completed'
        elif self.turns >= self.max_turns:
            self.terminal_reason = 'turn_limit'
        return self.observe()

    def result(self) -> dict:
        return {'version': VERSION, 'level': self.plan['level'], 'turns': self.turns,
                'terminal_reason': self.terminal_reason, 'completed_tasks': len(self.done),
                'invalid_actions': self.invalid_actions, 'oracle_min_turns': self._optimum,
                'extra_turns': self.turns - self._optimum if self.terminal_reason == 'completed' else None}
