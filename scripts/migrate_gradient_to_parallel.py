#!/usr/bin/env python3
"""Fork a *stopped*, checkpoint-clean sequential plan into a parallel plan.

Never stops the source process, alters it, calls a model, or retries attempts.
The source lock must be free and all previous receipts resolved.
"""
from __future__ import annotations
import argparse
import copy
import fcntl
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts import independent_gradient_calibration as sequential
from scripts import parallel_gradient_calibration as parallel

def migrate(source,target):
    sequential.configure();e=sequential.engine
    source_dir=e.path_for(source)
    if not source_dir.is_dir():raise ValueError('source missing')
    fd=os.open(source_dir/'.lock',os.O_CREAT|os.O_RDWR,0o600)
    with os.fdopen(fd,'r+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        _,original,st=e.load(source)
        if st.get('sealed'):raise ValueError('source must be unsealed')
        if any(rec.get('status')=='inflight' for rec in st['episodes'].values()):raise ValueError('unresolved episode')
        if any(receipt.get('status')=='inflight' for group in st['receipts'].values() for receipt in group):
            raise ValueError('unresolved receipt')
        if st['receipts']['holdout']:raise ValueError('source holdout already touched')
        allowed={'ready','completed','technical_error','action_limit'}
        if any(rec.get('status') not in allowed for rec in st['episodes'].values()):raise ValueError('unknown episode status')
        expected={}
        for split in ('dev','holdout'):
            for world,seed,model in e.specs(original,split):
                key=e.key_for(split,world,model);expected[key]=seed
                if key in st['episodes']:e.reconstruct(original,seed,st['episodes'][key])
        if not set(st['episodes']).issubset(expected):raise ValueError('unknown episode')
        counts={};errors={}
        for i,receipt in enumerate(st['receipts']['dev'],1):
            if receipt.get('number')!=i or receipt.get('episode') not in st['episodes']:
                raise ValueError('receipt mismatch')
            key=receipt['episode'];status=receipt.get('status')
            if status=='completed':counts[key]=counts.get(key,0)+1
            elif status=='technical_error':errors[key]=errors.get(key,0)+1
            else:raise ValueError('unknown receipt status')
        for key,rec in st['episodes'].items():
            if counts.get(key,0)!=len(rec.get('turns',[])):raise ValueError('receipts disagree with replay')
            if errors.get(key,0)!=(1 if rec['status']=='technical_error' else 0):raise ValueError('technical receipt mismatch')
        old_hash=e.digest(original);old_receipts=len(st['receipts']['dev'])
        input_used=sum(r.get('usage',{}).get('input_tokens',0) for r in st['receipts']['dev'])
        p=copy.deepcopy(original);next_state=copy.deepcopy(st)
        parallel.configure();e=parallel.engine
        p['source_sha256']=parallel.fingerprint(p['adapter'])
        p['parallel_migration']={'source_plan_sha256':old_hash,'sequential_dev_receipts':old_receipts,
                                 'scheduler':'single-coordinator-3-workers','same_prompt_and_game':True}
        next_state['plan_sha256']=e.digest(p)
        out=e.path_for(target);out.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        out.mkdir(mode=0o700,exist_ok=False)
        e.write(out/'plan.json',p);e.write(out/'state.json',next_state)
        e.write(out/'migration_audit.json',{'source':source,'target':target,'source_plan_sha256':old_hash,
                  'target_plan_sha256':next_state['plan_sha256'],'sequential_dev_receipts':old_receipts,
                  'reported_input_tokens_at_boundary':input_used,'max_calls_per_split':p['max_calls_per_split'],
                  'max_input_tokens_per_split':p['max_input_tokens_per_split'],
                  'dev_receipts_preserved':True,'holdout_receipts_preserved':True,
                  'note':'Same worlds, actions, game rules, prompt and limits; scheduler changes at receipt boundary. No call retried.'})
        _,loaded,verify=e.load(target)
        for key,seed in expected.items():
            if key in verify['episodes']:e.reconstruct(loaded,seed,verify['episodes'][key])
        if verify['receipts']!=st['receipts']:raise ValueError('receipt copy mismatch')
    print(f'Created private parallel fork {target}; preserved {old_receipts} resolved dev receipts and all episode journals. No model calls.')

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('source');ap.add_argument('target');args=ap.parse_args()
    migrate(args.source,args.target)

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,TypeError):
        print('Migration refused; source must be stopped, replayable and have no unresolved attempts.',file=sys.stderr);sys.exit(1)
