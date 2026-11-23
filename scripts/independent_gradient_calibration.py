#!/usr/bin/env python3
"""Three-model adventure pilot; a failed episode does not block the others.

Each attempt is checkpointed and failures are never retried. Plans, seeds and
receipts remain private. The prompt and scoring are inherited from gradient.
"""
from __future__ import annotations
import argparse
import fcntl
import hashlib
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts import gradient_codex_calibration as gradient

engine=gradient.engine
radical=gradient.radical
BASE=Path.home()/'.local/share/adndbench/independent-gradient-calibrations'

def fingerprint(adapter):
    h=hashlib.sha256()
    h.update(gradient.fingerprint(adapter).encode()+b'\0')
    h.update(Path(__file__).read_bytes())
    return h.hexdigest()

def configure():
    gradient.configure()
    radical.fingerprint=fingerprint
    engine.fingerprint=fingerprint
    engine.BASE=BASE

def run(name,split):
    d=engine.path_for(name);fd=__import__('os').open(d/'.lock',__import__('os').O_CREAT|__import__('os').O_RDWR,0o600)
    with __import__('os').fdopen(fd,'r+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        d,p,st=engine.load(name)
        if split=='holdout' and not st['sealed']:raise ValueError('seal before holdout')
        if split=='dev' and st['sealed']:raise ValueError('development closed after seal')
        if any(r.get('status')=='inflight' for r in st['episodes'].values()):
            raise ValueError('uncertain inflight attempt; inspect, do not retry')
        for world,seed,model in engine.specs(p,split):
            key=engine.key_for(split,world,model)
            if key not in st['episodes']:st['episodes'][key]={'status':'ready','turns':[]}
            engine.reconstruct(p,seed,st['episodes'][key])
        started=time.monotonic();stop=False
        while not stop:
            progress=False
            for world,seed,model in engine.specs(p,split):
                key=engine.key_for(split,world,model);rec=st['episodes'][key]
                if rec['status']!='ready':continue
                game,history=engine.reconstruct(p,seed,rec)
                if game.done:
                    rec['status']='completed';rec['result']=game.result();engine.write(d/'state.json',st);continue
                if len(rec['turns'])>=p['max_actions_per_game']:
                    rec['status']='action_limit';engine.write(d/'state.json',st);continue
                receipts=st['receipts'][split]
                if (len(receipts)>=p['max_calls_per_split'] or
                    sum(x.get('usage',{}).get('input_tokens',0) for x in receipts)>=p['max_input_tokens_per_split'] or
                    time.monotonic()-started>=p['max_wall_seconds_per_run']):
                    stop=True;break
                progress=True;obs=game.observe();rec['status']='inflight'
                receipt={'episode':key,'number':len(receipts)+1,'status':'inflight'}
                receipts.append(receipt);engine.write(d/'state.json',st)
                remaining=p['max_wall_seconds_per_run']-(time.monotonic()-started)
                answer=engine.call(engine.prompt(p,history,obs),model,min(p['call_timeout'],max(0.1,remaining)))
                if 'error' in answer:
                    rec['status']='technical_error';rec['technical_error']=answer['error'];receipt['status']='technical_error'
                    if 'usage' in answer:receipt['usage']=answer['usage']
                    engine.write(d/'state.json',st)
                    print(f'{split} world {world}: {model}, technical_error; episode not retried',flush=True)
                    continue
                action=engine.canonical_action(answer['action'],engine.actions(p,obs));game.step(action)
                rec['turns'].append({'observation_sha256':engine.digest(obs),'action':action})
                rec['status']='completed' if game.done else 'ready'
                if game.done:rec['result']=game.result()
                receipt.update(status='completed',usage=answer['usage']);engine.write(d/'state.json',st)
                print(f'{split} world {world}: {model}, {len(rec["turns"])} actions',flush=True)
            if not progress:break
        engine.write(d/'state.json',st)
    gradient.status(name)

def main():
    configure();ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='command',required=True)
    a=sub.add_parser('init');a.add_argument('name');a.add_argument('--dev-worlds',type=int,default=3);a.add_argument('--holdout-worlds',type=int,default=3)
    a.add_argument('--max-calls',type=int,default=1000);a.add_argument('--max-input-tokens',type=int,default=20000000)
    for command in ('status','seal'):
        a=sub.add_parser(command);a.add_argument('name')
    a=sub.add_parser('run');a.add_argument('name');a.add_argument('--split',choices=('dev','holdout'),required=True)
    args=ap.parse_args()
    if args.command=='init':
        config={'memory':'medium','navigation':'easy','quests':'hard','combat':'medium','party':True,'max_turns':160}
        radical.init(args.name,config,args.dev_worlds,args.holdout_worlds,160,args.max_calls,args.max_input_tokens,160)
    elif args.command=='status':gradient.status(args.name)
    elif args.command=='seal':engine.seal(args.name)
    else:run(args.name,args.split)

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,TypeError):
        print('Calibration stopped; inspect private state. No automatic retry.',file=sys.stderr);sys.exit(1)
