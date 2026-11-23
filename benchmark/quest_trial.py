"""Long multi-step quest planning with visible dependencies and irreversible choices.

A separate development protocol. No secret seed or optimal solution is included
in player observations. In contrast to exploration, this environment deliberately
reveals the quest ledger: it isolates action planning and resource interference.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Any
from benchmark.fixed_probes import _Stream

VERSION = 'quest-trial-0.1.0'
LEVELS = ('medium', 'hard', 'extreme')
# Each tuple is (parallel quest threads, actions per thread, optional dead-end trades).
PARAMETERS = {'medium': (2, 5, 2), 'hard': (3, 6, 3), 'extreme': (4, 7, 4)}
SYSTEM_PROMPT = (
    'Выполните главное поручение. На каждом ходу верните ровно один JSON-объект '
    '{"type":"perform","target":"ID"}, выбрав действие из журнала. Условия requires '
    'относятся к уже завершённым действиям, consumes — к текущему инвентарю, produces '
    'добавляет предметы. После выполнения действия расходуемые предметы исчезают; '
    'каждое действие выполняется не более одного раза. Выбирайте порядок и учитывайте '
    'последствия обменов; не все действия обязательны. Неверный ход тратит время. '
    'Успех — завершить действие goal до лимита. Все условия и эффекты видимы; '
    'других источников предметов и скрытых правил нет.'
)


def source_fingerprint() -> str:
    h=hashlib.sha256()
    for p in (Path(__file__),Path(__file__).with_name('fixed_probes.py')):
        h.update(p.name.encode()+b'\0'+p.read_bytes()+b'\0')
    return h.hexdigest()


def generate_plan(seed: str | int, level: str) -> dict:
    if not isinstance(seed, (str,int)) or isinstance(seed,bool): raise ValueError('invalid seed')
    if level not in PARAMETERS: raise ValueError('unknown difficulty')
    branches, depth, decoys = PARAMETERS[level]
    rng = _Stream(str(seed), VERSION + ':' + level)
    task_ids=[f'Q{i:02d}' for i in range(1,branches*depth+decoys+2)]
    token_ids=[f'предмет-{i:02d}' for i in range(1,branches*depth+decoys+1)]
    rng.shuffle(task_ids);rng.shuffle(token_ids)
    tasks=[]; chains=[]; tokens=[]
    for i in range(branches):
        chain=task_ids[i*depth:(i+1)*depth]
        items=token_ids[i*depth:(i+1)*depth]
        chains.append(chain);tokens.append(items)
    labels=('Исследовать след','Получить поручение','Найти предмет','Обменять предмет',
            'Изучить печать','Подготовить артефакт','Доставить находку')
    for i,chain in enumerate(chains):
        for j,qid in enumerate(chain):
            required=[chain[j-1]] if j else []
            # Later threads depend on progress in the preceding thread, while
            # remaining independent enough to create a nontrivial action order.
            if i and j==depth-2: required.append(chains[i-1][depth-3])
            tasks.append({'id':qid,'description':labels[j], 'requires':required,
                          'consumes':[] if j==0 else [tokens[i][j-1]],
                          'produces':[tokens[i][j]]})
    for i in range(decoys):
        # A legitimate optional transaction irreversibly spends a needed item.
        # Both its cost and the lack of a replacement are explicit in the ledger.
        at=depth-2
        tasks.append({'id':task_ids[branches*depth+i], 'description':'Обменять на побочную награду',
                      'requires':[chains[i][at-1]], 'consumes':[tokens[i][at-1]],
                      'produces':[token_ids[branches*depth+i]]})
    goal=task_ids[-1]
    tasks.append({'id':goal,'description':'Вернуть реликвии заказчику',
                  'requires':[chain[-1] for chain in chains],
                  'consumes':[items[-1] for items in tokens], 'produces':[]})
    rng.shuffle(tasks)
    return {'version':VERSION,'level':level,'tasks':tasks,'goal':goal,'initial_inventory':[]}


def _legal(task: dict, completed: frozenset[str], inventory: frozenset[str]) -> bool:
    return (task['id'] not in completed and set(task['requires']) <= completed
            and set(task['consumes']) <= inventory)


def oracle(game: 'QuestTrial', *, max_states: int = 250000) -> dict:
    """Exhaustive BFS on action effects from current state; never mutates the game.

    Capped search returns unknown, not an asserted impossibility. This has
    privileged access to the plan but the plan's content is in the quest ledger.
    """
    if type(max_states) is not int or max_states < 1: raise ValueError('invalid search cap')
    initial=(frozenset(game.completed),frozenset(game.inventory))
    q=deque([(initial,())]);seen={initial}
    while q:
        (done,items),path=q.popleft()
        if game.plan['goal'] in done:
            return {'status':'solved','actions':[{'type':'perform','target':i} for i in path], 'states':len(seen)}
        if len(path) >= game.max_turns - game.turn:
            continue
        for task in game.plan['tasks']:
            if not _legal(task,done,items): continue
            nxt=(done | {task['id']}, (items - set(task['consumes'])) | set(task['produces']))
            if nxt in seen: continue
            if len(seen)>=max_states:
                return {'status':'unknown','actions':None,'states':len(seen)}
            seen.add(nxt);q.append((nxt,path+(task['id'],)))
    return {'status':'unsolvable','actions':None,'states':len(seen)}


class QuestTrial:
    """A deterministic turn-based quest ledger with evolving inventory."""
    def __init__(self, seed: str | int, level: str = 'hard', max_turns: int | None = None):
        self.plan=generate_plan(seed,level)
        self.seed=str(seed);self.level=level
        branches,depth,_=PARAMETERS[level]
        self.optimal_turns=branches*depth+1
        limit=self.optimal_turns + {'medium':4,'hard':5,'extreme':6}[level] if max_turns is None else max_turns
        if type(limit) is not int or limit < 1: raise ValueError('invalid turn limit')
        self.max_turns=limit
        self.completed:set[str]=set();self.inventory:set[str]=set()
        self.turn=0;self.invalid_actions=0;self.done=False;self.terminal_reason=None
        self.last_event='Начало поручения.'

    def observe(self) -> dict:
        return {'version':VERSION,'goal':self.plan['goal'],
                'tasks':deepcopy(self.plan['tasks']),'completed':sorted(self.completed),
                'inventory':sorted(self.inventory),'turn':self.turn,'max_turns':self.max_turns,
                'last_event':self.last_event,'done':self.done,'rules':SYSTEM_PROMPT}

    def step(self,action:Any)->dict:
        if self.done: raise RuntimeError('episode is over')
        self.turn+=1
        target = action.get('target') if isinstance(action,dict) and set(action)=={'type','target'} and action.get('type')=='perform' and isinstance(action.get('target'),str) else None
        task=next((t for t in self.plan['tasks'] if t['id']==target),None)
        if task is not None and _legal(task,frozenset(self.completed),frozenset(self.inventory)):
            self.completed.add(task['id']);self.inventory.difference_update(task['consumes']);self.inventory.update(task['produces'])
            self.last_event=f"Выполнено {task['id']}; инвентарь изменён."
        else:
            self.invalid_actions+=1;self.last_event='Действие невозможно; условия или предметы отсутствуют.'
        if self.plan['goal'] in self.completed:
            self.done=True;self.terminal_reason='completed'
        elif self.turn>=self.max_turns:
            self.done=True;self.terminal_reason='turn_limit'
        return self.observe()

    def result(self)->dict:
        return {'version':VERSION,'level':self.level,'turns':self.turn,'max_turns':self.max_turns,
                'terminal_reason':self.terminal_reason,'completed':self.terminal_reason=='completed',
                'invalid_actions':self.invalid_actions,'completed_tasks':len(self.completed),
                'oracle_min_turns':self.optimal_turns,
                'extra_turns':self.turn-self.optimal_turns if self.terminal_reason=='completed' else None}
