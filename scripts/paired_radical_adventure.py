#!/usr/bin/env python3
"""Paired Codex runner for the integrated radical adventure.

Wraps paired_codex_calibration in this process only; does not alter existing
plans, runner code or running processes. See docs/paired-radical-adventure.md.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import hashlib
from pathlib import Path
import re
import secrets
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT))
from scripts import paired_codex_calibration as engine
from benchmark import radical_adventure as scenario

BASE = Path.home()/'.local/share/adndbench/paired-radical-adventures'
ADAPTER = 'radical_adventure'
_existing_canonical = engine.canonical_action
_existing_status = engine.status


def fingerprint(name):
    if name!=ADAPTER:raise ValueError('unknown adapter')
    folder=ROOT/'benchmark'
    files=('__init__.py','vector_harness.py','radical_adventure.py','quest_trial.py',
           'adventure_vectors.py','fixed_probes.py','party_combat.py','party_adventure.py')
    paths=[(name,folder/name) for name in files]+[
        ('paired_codex_calibration.py',ROOT/'scripts/paired_codex_calibration.py'),
        ('paired_radical_adventure.py',Path(__file__).resolve())]
    h=hashlib.sha256()
    for name,path in paths:h.update(name.encode()+b'\0'+path.read_bytes()+b'\0')
    return h.hexdigest()


def create_game(p,seed):
    if p['adapter']!=ADAPTER:raise ValueError('unknown adapter')
    return scenario.Game(seed,**p['game_config'])


def rule(p):
    if p['adapter']!=ADAPTER:raise ValueError('unknown adapter')
    return scenario.SYSTEM_PROMPT


def actions(p,obs):
    """Enumerate only known IDs; no hidden map, answers or remote characters."""
    result=[{'type':'talk'}]+[{'type':'move','direction':d} for d in ('north','east','south','west')]
    result += [{'type':'perform','target':t['id']} for t in obs.get('tasks',[])]
    result += [{'type':'recruit','candidate':c['id']} for c in obs.get('party',{}).get('candidates_here',[])]
    # An example shape, not an enumeration of possible codes. The one-time
    # clue remains the only source of the actual code and its length.
    result += [{'type':'unlock','code':'sun-moon'}]
    battle=obs.get('battle')
    if battle:
        members=[m['id'] for m in battle['party']['members']]
        enemies=[e['id'] for e in battle['enemies']]
        for actor in members:
            for kind in ('strike','blast'):
                result += [{'type':kind,'actor':actor,'target':target} for target in enemies]
            for kind in ('guard','heal'):
                result += [{'type':kind,'actor':actor,'target':target} for target in members]
    return result


def canonical(raw,allowed):
    if isinstance(raw,dict) and set(raw)=={'type','code'} and raw.get('type')=='unlock' and isinstance(raw.get('code'),str):
        code=raw['code']
        # A syntactically valid code must be preserved for game scoring. Other
        # strings become one guaranteed wrong code, consuming the same attempt.
        return {'type':'unlock','code':code if re.fullmatch(r'(?:sun|moon|star|tree)(?:-(?:sun|moon|star|tree)){0,3}',code) else '__invalid_code__'}
    if isinstance(raw,dict) and set(raw)=={'type','candidate'} and raw.get('type')=='recruit' and raw.get('candidate') in ('warden','medic','mage'):
        return dict(raw)
    return _existing_canonical(raw,allowed)


def status(name):
    # Expose only the explicitly chosen configuration, alongside safe aggregates.
    _,p,_=engine.load(name)
    output=io.StringIO()
    with contextlib.redirect_stdout(output):_existing_status(name)
    result=json.loads(output.getvalue())
    result['game_config']=p['game_config']
    print(json.dumps(result,ensure_ascii=False,indent=2))


def configure():
    # Module globals live in this process and do not alter the running base CLI.
    engine.BASE=BASE
    engine.fingerprint=fingerprint
    engine.create_game=create_game
    engine.rule=rule
    engine.actions=actions
    engine.canonical_action=canonical
    engine.status=status


def init(name,game_config,dev_worlds,holdout_worlds,max_actions,max_calls,max_input_tokens,context_turns):
    if not (1<=dev_worlds<=10 and 1<=holdout_worlds<=10 and 1<=max_actions<=300
            and 1<=max_calls<=1000 and 1<=max_input_tokens<=20000000 and 1<=context_turns<=300):
        raise ValueError('invalid bounds')
    # The code is given once; preserve the initial observation until either
    # the game or explicitly bounded pilot is over.
    if context_turns < min(max_actions,game_config['max_turns']):
        raise ValueError('history window could discard the one-time code')
    seeds=[]
    while len(seeds)<dev_worlds+holdout_worlds:
        s=secrets.token_hex(16)
        if s not in seeds:seeds.append(s)
    p={'version':engine.VERSION,'adapter':ADAPTER,'axis':'radical-adventure','level':'custom',
       'game_config':dict(game_config),'seeds':{'dev':seeds[:dev_worlds],'holdout':seeds[dev_worlds:]},
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
    print(f'Created private integrated plan: {dev_worlds} dev and {holdout_worlds} holdout worlds; no model calls.')


def main():
    configure()
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    a=sub.add_parser('init');a.add_argument('name')
    a.add_argument('--memory',choices=('easy','medium','hard','extreme'),default='medium')
    a.add_argument('--navigation',choices=('easy','medium','hard'),default='medium')
    a.add_argument('--quests',choices=('medium','hard','extreme'),default='hard')
    a.add_argument('--combat',choices=('off','easy','medium','hard'),default='off')
    a.add_argument('--party',choices=('on','off'),default='off')
    a.add_argument('--max-turns',type=int,default=300)
    a.add_argument('--dev-worlds',type=int,default=1);a.add_argument('--holdout-worlds',type=int,default=3)
    a.add_argument('--max-actions',type=int,default=100);a.add_argument('--context-turns',type=int,default=100)
    a.add_argument('--max-calls',type=int,default=250);a.add_argument('--max-input-tokens',type=int,default=6000000)
    for command in ('seal','status'):
        a=sub.add_parser(command);a.add_argument('name')
    a=sub.add_parser('run');a.add_argument('name');a.add_argument('--split',choices=('dev','holdout'),required=True)
    args=parser.parse_args()
    if args.command=='init':
        config={'memory':args.memory,'navigation':args.navigation,'quests':args.quests,
                'combat':args.combat,'party':args.party=='on','max_turns':args.max_turns}
        init(args.name,config,args.dev_worlds,args.holdout_worlds,args.max_actions,args.max_calls,args.max_input_tokens,args.context_turns)
    elif args.command=='seal':engine.seal(args.name)
    elif args.command=='status':engine.status(args.name)
    else:engine.run(args.name,args.split)

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,TypeError):
        print('Calibration stopped; inspect private state. No automatic retry.',file=sys.stderr);sys.exit(1)
