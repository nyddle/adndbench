#!/usr/bin/env python3
"""Three-model fixed party/combat diagnostics; dev only, no holdout claims."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import secrets
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT))
from scripts import paired_codex_calibration as engine
from benchmark import party_tactics_probe as probe

BASE=Path.home()/'.local/share/adndbench/three-model-party-tactics'
MODELS=('gpt-6-luna','gpt-6.2-sol','gpt-6.2-astra')
ADAPTER='party_tactics_probe'


def fingerprint(name):
    if name!=ADAPTER: raise ValueError('unknown adapter')
    folder=ROOT/'benchmark'
    files=('__init__.py','vector_harness.py','party_combat.py','party_tactics_probe.py')
    paths=[(n,folder/n) for n in files]+[('paired_codex_calibration.py',ROOT/'scripts/paired_codex_calibration.py'),('three_model_party_tactics.py',Path(__file__).resolve())]
    h=hashlib.sha256()
    for label,path in paths: h.update(label.encode()+b'\0'+path.read_bytes()+b'\0')
    return h.hexdigest()


def create_game(p,seed):
    if p['adapter']!=ADAPTER: raise ValueError('invalid adapter')
    return probe.Game(seed,p['axis'],p['level'])


def rule(p):
    if p['adapter']!=ADAPTER: raise ValueError('invalid adapter')
    return probe.SYSTEM_PROMPT


def actions(p,obs): return probe.allowed_actions(p['axis'],obs)


def status(name):
    _,p,st=engine.load(name); by_model={}
    for model in MODELS:
        rec=st['episodes'].get(engine.key_for('dev',1,model),{'status':'pending','turns':[]})
        g,_=engine.reconstruct(p,p['seeds']['dev'][0],rec)
        result=g.result() if rec['status']=='completed' else None
        if result is not None: result={k:v for k,v in result.items() if k!='seed'}
        by_model[model]={'status':rec['status'],'result':result}
    receipts=st['receipts']['dev']
    print(json.dumps({'protocol':probe.VERSION,'axis':p['axis'],'level':p['level'],
      'cases':1,'models':by_model,'effort':engine.EFFORT,'calls':len(receipts),
      'reported_input_tokens':sum(r.get('usage',{}).get('input_tokens',0) for r in receipts),
      'note':'One fixed dev case per model, not independent worlds. No holdout or population accuracy. '
             'Party choice checks existence of a winning strategy, not actual execution. '
             'Technical and external limits are not losses. Tool use audited; filesystem not fully isolated.'},ensure_ascii=False,indent=2))


def configure():
    engine.BASE=BASE;engine.MODELS=MODELS;engine.fingerprint=fingerprint
    engine.create_game=create_game;engine.rule=rule;engine.actions=actions;engine.status=status


def init(name,axis,level,max_calls,max_input_tokens):
    if not (1<=max_calls<=200 and 1<=max_input_tokens<=5000000): raise ValueError('bad budget')
    probe.enemies(axis,level)
    max_actions=4 if axis=='party' else 12
    p={'version':engine.VERSION,'adapter':ADAPTER,'axis':axis,'level':level,
       'seeds':{'dev':[secrets.token_hex(16)],'holdout':[]},'models':list(MODELS),
       'reasoning_effort':engine.EFFORT,'cli_version':engine.cli_version(),
       'context_turns':max_actions,'max_actions_per_game':max_actions,
       'max_calls_per_split':max_calls,'max_input_tokens_per_split':max_input_tokens,
       'call_timeout':engine.TIMEOUT,'max_wall_seconds_per_run':engine.MAX_WALL,
       'source_sha256':fingerprint(ADAPTER),'system_prompt':probe.SYSTEM_PROMPT}
    create_game(p,p['seeds']['dev'][0]).observe()
    d=engine.path_for(name);d.mkdir(parents=True,mode=0o700,exist_ok=True)
    if d.stat().st_mode&0o077 or any(d.iterdir()): raise ValueError('requires new owner-only directory')
    engine.write(d/'plan.json',p)
    engine.write(d/'state.json',{'sealed':False,'plan_sha256':engine.digest(p),'episodes':{},'receipts':{'dev':[],'holdout':[]}})
    print('Created private fixed-case dev plan; no model calls and no independent holdout.')


def main():
    configure();ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='command',required=True)
    a=sub.add_parser('init');a.add_argument('name');a.add_argument('--axis',choices=('party','tactics'),required=True)
    a.add_argument('--level',choices=('fixed','one','two','three'),required=True)
    a.add_argument('--max-calls',type=int,default=45);a.add_argument('--max-input-tokens',type=int,default=1500000)
    for command in ('run','status'):
        a=sub.add_parser(command);a.add_argument('name')
    args=ap.parse_args()
    if args.command=='init':init(args.name,args.axis,args.level,args.max_calls,args.max_input_tokens)
    elif args.command=='status':status(args.name)
    else:engine.run(args.name,'dev')


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,TypeError):
        print('Calibration stopped; inspect private state. No automatic retry.',file=sys.stderr);sys.exit(1)
