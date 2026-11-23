"""Diagnostic 0–100 progress score for radical-adventure-0.1.0.

The evaluator owns the game and canonical action journal. It replays that
journal to award meaningful visits only at reachable mandatory objectives.
This score supplements, never replaces, the binary terminal outcome.
"""
from __future__ import annotations
from copy import deepcopy
from typing import Any
from benchmark.radical_adventure import Game, VERSION as ENGINE_VERSION
from benchmark.quest_trial import _legal

VERSION='radical-score-0.1.0'
WEIGHTS={'mandatory_quests':40,'objective_locations':15,'code':10,'combat':15,'goal':20}


def required_task_ids(plan:dict)->set[str]:
    """Transitive closure of prerequisites *and* producers of consumed items.

    Single producers and known initial inventory are required for an unambiguous
    graph. Arbitrary optional tasks are not rewarded.
    """
    tasks={t['id']:t for t in plan['tasks']}
    if len(tasks)!=len(plan['tasks']) or plan['goal'] not in tasks:
        raise ValueError('invalid quest IDs')
    producers={}
    for task in tasks.values():
        for item in task['produces']:
            if item in producers:raise ValueError('item has multiple producers')
            producers[item]=task['id']
    initial=set(plan.get('initial_inventory',[]));pending=[plan['goal']];required=set()
    while pending:
        item=pending.pop()
        if item in required:continue
        if item not in tasks:raise ValueError('unknown prerequisite')
        required.add(item);task=tasks[item];pending.extend(task['requires'])
        for resource in task['consumes']:
            if resource not in initial:
                if resource not in producers:raise ValueError('missing item producer')
                pending.append(producers[resource])
    return required


def _state(game:Game)->dict[str,Any]:
    battle=game.battle
    return {'result':game.result(), 'observation':game.observe(),
            'visited':sorted(game.visited), 'completed':sorted(game.quest.completed),
            'inventory':sorted(game.quest.inventory), 'party':game.members.snapshot(),
            'unlocked':game.unlocked, 'encounter_won':game.encounter_won,
            'battle':None if battle is None else {'status':battle.status,'round':battle.round,
                'enemies':deepcopy(battle.enemies), 'braced':battle.braced}}


def _replay(game:Game,actions:list[dict])->tuple[Game,set]:
    if not isinstance(game,Game) or not isinstance(actions,list):
        raise ValueError('expected radical adventure and a list of actions')
    replay=Game(game.seed,memory=game.memory,navigation=game.navigation,quests=game.quests,
                combat=game.combat,party=game.party_enabled,max_allies=game.members.max_allies,
                max_turns=game.max_turns)
    required=required_task_ids(replay.quest.plan)
    tasks={t['id']:t for t in replay.quest.plan['tasks']}
    reached=set()
    def observe_progress():
        # Only locations with revealed, currently actionable mandatory work
        # count. Revisiting, optional work and pre-brief wandering add nothing.
        if not replay.briefed:return
        for key in required:
            t=tasks[key]
            if (replay.task_rooms[key]==replay.position and
                _legal(t,frozenset(replay.quest.completed),frozenset(replay.quest.inventory))):
                reached.add(replay.position)
    for action in actions:
        if replay.done:raise ValueError('actions continue after terminal outcome')
        observe_progress();replay.step(action)
    observe_progress()
    if _state(replay)!=_state(game):raise ValueError('journal does not reproduce game state')
    return replay,reached


def score(game:Game,actions:list[dict])->dict[str,Any]:
    """Return transparent partial score, excluding unresolved nonterminal games.

    A game ended by dead_end, death, incorrect_code, combat_limit or turn_limit
    remains a terminal *game* outcome and receives partial credit. API errors,
    runner limits, interruptions, and in-flight requests cannot be judged here:
    the caller must retain their separate status and exclude them from standings.
    """
    game,reached=_replay(game,actions)
    plan=game.quest.plan;required=required_task_ids(plan);goal=plan['goal']
    stages=required-{goal};complete=game.quest.completed & stages
    rooms={game.task_rooms[t] for t in required}
    active_rooms=reached & rooms
    total_hp = sum(e['max_hp'] for e in game.battle.enemies) if game.battle else 0
    lost_hp = sum(e['max_hp']-e['hp'] for e in game.battle.enemies) if game.battle else 0
    if game.combat=='off': combat={'status':'not_applicable','count':None,'total':None,'fraction':None}
    elif game.battle is None: combat={'status':'not_attempted','count':0,'total':None,'fraction':0.0}
    else:
        statuses={'ongoing':'in_progress','victory':'completed','defeat':'failed','timeout':'failed'}
        combat={'status':statuses[game.battle.status],'count':lost_hp,'total':total_hp,
                'fraction':lost_hp/total_hp}
    components={
       'mandatory_quests':{'status':'completed' if len(complete)==len(stages) else ('partial' if complete else 'not_started'),
                           'count':len(complete),'total':len(stages),'fraction':len(complete)/len(stages) if stages else 1.0},
       'objective_locations':{'status':'completed' if len(active_rooms)==len(rooms) else ('partial' if active_rooms else 'not_attempted'),
                              'count':len(active_rooms),'total':len(rooms),'fraction':len(active_rooms)/len(rooms) if rooms else 1.0},
       'code':{'status':'completed' if game.unlocked else ('failed' if game.terminal_reason=='incorrect_code' else 'not_attempted'),
               'count':int(game.unlocked),'total':1,'fraction':float(game.unlocked)},
       'combat':combat,
       'goal':{'status':'completed' if game.terminal_reason=='completed' else ('not_completed' if game.done else 'not_attempted'),
               'count':int(game.terminal_reason=='completed'),'total':1,'fraction':float(game.terminal_reason=='completed')},
    }
    active=sum(w for key,w in WEIGHTS.items() if components[key]['fraction'] is not None)
    for key,part in components.items():
        fraction=part['fraction']
        part['weight']=round(100*WEIGHTS[key]/active,6) if fraction is not None else None
        part['earned']=round(100*WEIGHTS[key]*fraction/active,6) if fraction is not None else None
    points=round(sum(p['earned'] for p in components.values() if p['earned'] is not None),2)
    return {'version':VERSION,'engine_version':ENGINE_VERSION, 'complete_episode':game.done,
            'terminal_reason':game.terminal_reason, 'win':game.terminal_reason=='completed' if game.done else None,
            'score':points if game.done else None, 'provisional_score':points,
            'components':components,
            'note':'Diagnostic progress; compare only identical scenarios and weights. '
                   'Incomplete or technical episodes must not be counted as zero.'}
