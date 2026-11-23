#!/usr/bin/env python3
"""Three-class paired calibration on integrated radical adventures.

A process-local wrapper around paired_radical_adventure and its replay-safe
executor; no changes to running paired experiments. No API calls on init/status.
"""
from __future__ import annotations
import argparse
import copy
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT))
from scripts import paired_radical_adventure as radical
from benchmark import radical_score

engine=radical.engine
BASE=Path.home()/'.local/share/adndbench/gradient-codex-calibrations'
MODELS=('gpt-6-luna','gpt-6.2-sol','gpt-6.2-astra')
_base_fingerprint=radical.fingerprint
_base_rule=radical.rule
HISTORY_PROTOCOL='deduplicated-stable-fields-0.1.0'
HISTORY_FIELDS=('tasks','scouting','combat_rules')
HISTORY_NOTICE=('Past observations retain all actions and changing fields. Repeated tasks, scouting and combat_rules fields may be omitted only when identical to the current observation; their first occurrence is preserved. Current observation is complete.')


def fingerprint(adapter_name):
    h=hashlib.sha256()
    h.update(_base_fingerprint(adapter_name).encode()+b'\0')
    for p in (Path(__file__).resolve(), ROOT/'benchmark/radical_score.py'):
        h.update(p.name.encode()+b'\0'+p.read_bytes()+b'\0')
    return h.hexdigest()


def rule(p):
    return _base_rule(p) + '\nHistory protocol ' + HISTORY_PROTOCOL + ': ' + HISTORY_NOTICE


def compact_history(history, current):
    """Remove only duplicate immutable field values also present currently.

    First occurrence, all different values, and every changing field remain.
    Inputs are not mutated. This is a distinct prompt protocol, not lossless
    identity at the JSON level and not interchangeable with earlier pilots.
    """
    previous={field:None for field in HISTORY_FIELDS}
    result=[]
    for entry in history:
        obs=copy.deepcopy(entry['observation'])
        for field in HISTORY_FIELDS:
            if field not in obs:
                previous[field]=None
                continue
            value_digest=engine.digest(obs[field])
            repeated=value_digest == previous[field]
            previous[field]=value_digest
            if repeated and field in current and obs[field] == current[field]:
                del obs[field]
        result.append({'observation':obs,'action':copy.deepcopy(entry['action'])})
    return result


def prompt(p,history,obs):
    n=p['context_turns']
    visible=history[-max(0,n-1):] if n>1 else []
    public={'rules':p['system_prompt'],'past_turns':compact_history(visible,obs),
            'current_observation':obs,'possible_action_shapes':engine.actions(p,obs)}
    return ('You are a subject in a turn-based game. Do not use any tools, commands, files, browsers '
            'or external information. Return exactly one JSON action, without Markdown, prose or notes. '
            'Possible actions are syntactic forms and may not be legal now.\n' + engine.encode(public).decode())


def status(name):
    _,p,st=engine.load(name)
    groups=[]
    for split in ('dev','holdout'):
        model_stats={}
        for model in MODELS:
            terminal_scores=[]; statuses=Counter();reasons=Counter()
            for world,seed,current in engine.specs(p,split):
                if current!=model:continue
                rec=st['episodes'].get(engine.key_for(split,world,model),{'status':'pending','turns':[]})
                game,_=engine.reconstruct(p,seed,rec)
                statuses[rec['status']]+=1
                if rec['status']=='completed':
                    result=game.result();reasons[result['terminal_reason']]+=1
                    terminal_scores.append(radical_score.score(game, [x['action'] for x in rec['turns']])['score'])
            count=len(terminal_scores)
            model_stats[model]={'planned':len(p['seeds'][split]),'statuses':dict(statuses),
                'terminal_reasons':dict(reasons), 'terminal_games':count, 'wins':reasons['completed'],
                'win_rate_terminal':round(reasons['completed']/count,4) if count else None,
                'terminal_scores':terminal_scores,
                'mean_terminal_score':round(statistics.mean(terminal_scores),2) if terminal_scores else None}
        pairs=Counter()
        per_world=[]
        for world,seed,current in engine.specs(p,split):
            if current!=MODELS[0]:continue
            vals={}
            for model in MODELS:
                rec=st['episodes'].get(engine.key_for(split,world,model),{'status':'pending','turns':[]})
                game,_=engine.reconstruct(p,seed,rec)
                graded = radical_score.score(game, [x['action'] for x in rec['turns']]) if rec['status']=='completed' else None
                vals[model]={'status':rec['status'],
                    'score':graded['score'] if graded else None,
                    'components':graded.get('components') if graded else None,
                    'terminal_reason':game.result()['terminal_reason'] if graded else None}
            if all(v['score'] is not None for v in vals.values()):
                luna,sol,astra=(vals[m]['score'] for m in MODELS)
                pairs['all_terminal']+=1
                pairs['strict_ascending']+=int(luna<sol<astra)
                pairs['astra_above_luna']+=int(astra>luna)
                pairs['all_equal']+=int(luna==sol==astra)
            else:pairs['incomplete']+=1
            per_world.append({'world':world,'models':vals})
        receipts=st['receipts'][split]
        groups.append({'split':split,'models':model_stats,'complete_worlds':dict(pairs),
                       'worlds':per_world,'calls':len(receipts),
                       'reported_input_tokens':sum(x.get('usage',{}).get('input_tokens',0) for x in receipts),
                       'unknown_usage_calls':sum('usage' not in x for x in receipts)})
    out={'axis':p['axis'],'level':p['level'],'game_config':p['game_config'],'models':list(MODELS),
         'effort':engine.EFFORT,'context_turns':p['context_turns'],'sealed':st['sealed'],
         'score_protocol':radical_score.VERSION,'history_protocol':HISTORY_PROTOCOL,'groups':groups,
         'note':'Score is only aggregated for terminal games. Truncated or technical outcomes are incomplete, not zero. '
                'Codex tool use audited but filesystem is not fully isolated. One world is not a model ranking.'}
    print(json.dumps(out,ensure_ascii=False,indent=2))


def configure():
    radical.configure()
    radical.fingerprint=fingerprint
    radical.rule=rule
    engine.rule=rule
    engine.prompt=prompt
    engine.fingerprint=fingerprint
    engine.MODELS=MODELS
    engine.BASE=BASE
    engine.status=status


def main():
    configure()
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='command',required=True)
    a=sub.add_parser('init');a.add_argument('name')
    a.add_argument('--memory',choices=('easy','medium','hard','extreme'),default='medium')
    a.add_argument('--navigation',choices=('easy','medium','hard'),default='medium')
    a.add_argument('--quests',choices=('medium','hard','extreme'),default='hard')
    a.add_argument('--combat',choices=('off','easy','medium','hard'),default='off')
    a.add_argument('--party',choices=('on','off'),default='off')
    a.add_argument('--max-turns',type=int,default=300)
    a.add_argument('--dev-worlds',type=int,default=1);a.add_argument('--holdout-worlds',type=int,default=3)
    a.add_argument('--max-actions',type=int,default=100);a.add_argument('--context-turns',type=int,default=100)
    a.add_argument('--max-calls',type=int,default=350);a.add_argument('--max-input-tokens',type=int,default=8000000)
    for command in ('seal','status'):
        a=sub.add_parser(command);a.add_argument('name')
    a=sub.add_parser('run');a.add_argument('name');a.add_argument('--split',choices=('dev','holdout'),required=True)
    args=ap.parse_args()
    if args.command=='init':
        config={'memory':args.memory,'navigation':args.navigation,'quests':args.quests,
                'combat':args.combat,'party':args.party=='on','max_turns':args.max_turns}
        radical.init(args.name,config,args.dev_worlds,args.holdout_worlds,args.max_actions,args.max_calls,args.max_input_tokens,args.context_turns)
    elif args.command=='seal':engine.seal(args.name)
    elif args.command=='status':status(args.name)
    else:engine.run(args.name,args.split)

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,TypeError):
        print('Calibration stopped; inspect private state. No automatic retry.',file=sys.stderr);sys.exit(1)
