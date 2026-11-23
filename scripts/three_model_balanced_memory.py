#!/usr/bin/env python3
"""Compare three model classes on the same balanced short-memory dev worlds.

A process-local wrapper around the replay-safe paired executor. Existing runs,
source plans and holdout pools are not modified. See docs/three-model-balanced-memory.md.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import importlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT))
from scripts import paired_intermediate_memory as middle
engine=middle.engine
BASE=Path.home()/'.local/share/adndbench/three-model-balanced-memory'
ADAPTER='balanced_short_memory'
AXIS='memory-compact'
LEVELS=('s4','s6','s8')
MODELS=('gpt-6-luna','gpt-6.2-sol','gpt-6.2-astra')


def module():return importlib.import_module('benchmark.balanced_short_memory')


def fingerprint(name):
    if name!=ADAPTER:raise ValueError('invalid adapter')
    folder=ROOT/'benchmark'
    files=('__init__.py','vector_harness.py','fixed_probes.py','hard_memory_navigation.py','balanced_short_memory.py')
    paths=[(name,folder/name) for name in files]+[
        ('paired_codex_calibration.py',ROOT/'scripts/paired_codex_calibration.py'),
        ('paired_intermediate_memory.py',ROOT/'scripts/paired_intermediate_memory.py'),
        ('three_model_balanced_memory.py',Path(__file__).resolve())]
    h=hashlib.sha256()
    for label,path in paths:h.update(label.encode()+b'\0'+path.read_bytes()+b'\0')
    return h.hexdigest()


def status(name):
    _,p,st=engine.load(name)
    groups=[]
    for split in ('dev','holdout'):
        by_model={}
        for model in MODELS:
            outcomes=[]; statuses=Counter()
            for world,seed,cur in engine.specs(p,split):
                if cur!=model:continue
                rec=st['episodes'].get(engine.key_for(split,world,model),{'status':'pending','turns':[]})
                game,_=engine.reconstruct(p,seed,rec);statuses[rec['status']]+=1
                if rec['status']=='completed':outcomes.append(game.result()['terminal_reason'])
            wins=outcomes.count('completed')
            by_model[model]={'planned':len(p['seeds'][split]),'statuses':dict(statuses),'terminal_games':len(outcomes),
                             'outcomes':dict(Counter(outcomes)),'correct':wins,
                             'accuracy_terminal':round(wins/len(outcomes),4) if outcomes else None}
        worlds=[];complete=0
        for world,seed,current in engine.specs(p,split):
            if current!=MODELS[0]:continue
            values={}
            for model in MODELS:
                rec=st['episodes'].get(engine.key_for(split,world,model),{'status':'pending','turns':[]})
                game,_=engine.reconstruct(p,seed,rec)
                values[model]={'status':rec['status'],
                               'outcome':game.result()['terminal_reason'] if rec['status']=='completed' else None}
            complete+=int(all(v['status']=='completed' for v in values.values()))
            worlds.append({'world':world,'models':values})
        receipts=st['receipts'][split]
        groups.append({'split':split,'models':by_model,'complete_triples':complete,'worlds':worlds,
                       'calls':len(receipts),'reported_input_tokens':sum(r.get('usage',{}).get('input_tokens',0) for r in receipts),
                       'unknown_usage_calls':sum('usage' not in r for r in receipts)})
    print(json.dumps({'protocol':module().VERSION,'level':p['level'],'models':list(MODELS),
          'effort':engine.EFFORT,'context_turns':p['context_turns'],'sealed':st['sealed'],'groups':groups,
          'note':'Exploratory dev/holdout; missing and technical episodes are not wrong answers. '
                 'Codex tool use audited; filesystem not fully isolated. No hidden seeds in status.'},ensure_ascii=False,indent=2))


def configure(level):
    if level not in LEVELS:raise ValueError('unknown level')
    # Globals are changed only inside this process, never in source files or
    # already running processes.
    middle.BASE=BASE;middle.ADAPTER=ADAPTER;middle.AXIS=AXIS;middle.LEVEL=level
    middle.MIN_ACTIONS=4;middle.EXTRA_ALLOWED_ACTIONS=4;middle.fingerprint=fingerprint;middle.module=module
    middle.configure();engine.MODELS=MODELS;engine.status=status


def configure_existing(name):
    # Read only the public level from the private plan; load later verifies its SHA.
    engine.BASE=BASE; d=engine.path_for(name)
    p=json.loads((d/'plan.json').read_text())
    configure(p['level'])


def main():
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='command',required=True)
    a=sub.add_parser('init');a.add_argument('name');a.add_argument('--level',choices=LEVELS,default='s4')
    a.add_argument('--dev-worlds',type=int,default=2);a.add_argument('--holdout-worlds',type=int,default=3)
    a.add_argument('--max-actions',type=int,default=8);a.add_argument('--context-turns',type=int,default=8)
    a.add_argument('--max-calls',type=int,default=30);a.add_argument('--max-input-tokens',type=int,default=850000)
    for command in ('run','status','seal'):
        a=sub.add_parser(command);a.add_argument('name')
        if command=='run':a.add_argument('--split',choices=('dev','holdout'),required=True)
    args=ap.parse_args()
    if args.command=='init':
        configure(args.level)
        middle.init(args.name,args.dev_worlds,args.holdout_worlds,args.max_actions,args.max_calls,args.max_input_tokens,args.context_turns)
    else:
        configure_existing(args.name)
        if args.command=='seal':engine.seal(args.name)
        elif args.command=='status':status(args.name)
        else:engine.run(args.name,args.split)

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,TypeError):
        print('Calibration stopped; inspect private state. No automatic retry.',file=sys.stderr);sys.exit(1)
