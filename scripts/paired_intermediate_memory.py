#!/usr/bin/env python3
"""Separate paired Codex runner for intermediate grouped-exchange memory.

This wraps the existing executor only in this process; it does not alter any
running experiment. See docs/paired-intermediate-memory.md.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib
from pathlib import Path
import secrets
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT))
from scripts import paired_codex_calibration as engine

BASE=Path.home()/'.local/share/adndbench/paired-intermediate-memory'
ADAPTER='intermediate_memory'
AXIS='memory-compact'
LEVEL='medium'
MIN_ACTIONS=6
EXTRA_ALLOWED_ACTIONS=4


def module():return importlib.import_module('benchmark.intermediate_memory')


def fingerprint(name):
    if name != ADAPTER:raise ValueError('unknown adapter')
    folder=ROOT/'benchmark'
    files=('__init__.py','vector_harness.py','fixed_probes.py','hard_memory_navigation.py','intermediate_memory.py')
    paths=[(name,folder/name) for name in files]+[
        ('paired_codex_calibration.py',ROOT/'scripts/paired_codex_calibration.py'),
        ('paired_intermediate_memory.py',Path(__file__).resolve())]
    h=hashlib.sha256()
    for name,path in paths:h.update(name.encode()+b'\0'+path.read_bytes()+b'\0')
    return h.hexdigest()


def create_game(p,seed):
    if p['adapter'] != ADAPTER or p['axis'] != AXIS or p['level'] != LEVEL:raise ValueError('invalid adapter')
    return module().create_game(AXIS,seed,LEVEL)


def rule(p):
    if p['adapter'] != ADAPTER:raise ValueError('invalid adapter')
    return module().SYSTEM_PROMPT


def actions(p,obs):
    if p['adapter'] != ADAPTER:raise ValueError('invalid adapter')
    return module().allowed_actions(AXIS,obs)


def configure():
    # Python module globals are process-local and cannot affect another run.
    engine.BASE=BASE
    engine.fingerprint=fingerprint
    engine.create_game=create_game
    engine.rule=rule
    engine.actions=actions


def init(name,dev_worlds,holdout_worlds,max_actions,max_calls,max_input_tokens,context_turns):
    if not (1<=dev_worlds<=10 and 1<=holdout_worlds<=10 and MIN_ACTIONS<=max_actions<=120
            and 1<=max_calls<=1000 and 1<=max_input_tokens<=20000000 and 1<=context_turns<=120):
        raise ValueError('invalid bounds')
    # All initial assignments and exchange groups must fit in model context,
    # even if it makes invalid actions until its configured limit.
    if context_turns < min(max_actions,MIN_ACTIONS+EXTRA_ALLOWED_ACTIONS):
        raise ValueError('history window could hide initial assignment')
    seeds=[]
    while len(seeds)<dev_worlds+holdout_worlds:
        seed=secrets.token_hex(16)
        if seed not in seeds:seeds.append(seed)
    p={'version':engine.VERSION,'adapter':ADAPTER,'axis':AXIS,'level':LEVEL,
       'seeds':{'dev':seeds[:dev_worlds],'holdout':seeds[dev_worlds:]},
       'models':list(engine.MODELS),'reasoning_effort':engine.EFFORT,'cli_version':engine.cli_version(),
       'context_turns':context_turns,'max_actions_per_game':max_actions,'max_calls_per_split':max_calls,
       'max_input_tokens_per_split':max_input_tokens,'call_timeout':engine.TIMEOUT,
       'max_wall_seconds_per_run':engine.MAX_WALL,'source_sha256':fingerprint(ADAPTER),
       'system_prompt':rule({'adapter':ADAPTER})}
    for seed in seeds:create_game(p,seed).observe()
    d=engine.path_for(name);d.mkdir(parents=True,mode=0o700,exist_ok=True)
    if d.stat().st_mode&0o077 or any(d.iterdir()):raise ValueError('requires new owner-only directory')
    engine.write(d/'plan.json',p)
    engine.write(d/'state.json',{'sealed':False,'plan_sha256':engine.digest(p),'episodes':{},'receipts':{'dev':[],'holdout':[]}})
    print(f'Created private intermediate-memory plan: {dev_worlds} dev and {holdout_worlds} holdout worlds; no model calls.')


def main():
    configure()
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='command',required=True)
    a=sub.add_parser('init');a.add_argument('name');a.add_argument('--dev-worlds',type=int,default=2)
    a.add_argument('--holdout-worlds',type=int,default=3);a.add_argument('--max-actions',type=int,default=10)
    a.add_argument('--context-turns',type=int,default=10);a.add_argument('--max-calls',type=int,default=45)
    a.add_argument('--max-input-tokens',type=int,default=1200000)
    for command in ('seal','status'):
        a=sub.add_parser(command);a.add_argument('name')
    a=sub.add_parser('run');a.add_argument('name');a.add_argument('--split',choices=('dev','holdout'),required=True)
    args=ap.parse_args()
    if args.command=='init':init(args.name,args.dev_worlds,args.holdout_worlds,args.max_actions,args.max_calls,args.max_input_tokens,args.context_turns)
    elif args.command=='seal':engine.seal(args.name)
    elif args.command=='status':engine.status(args.name)
    else:engine.run(args.name,args.split)

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,TypeError):
        print('Calibration stopped; inspect private state. No automatic retry.',file=sys.stderr);sys.exit(1)
