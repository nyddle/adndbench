#!/usr/bin/env python3
"""Run Sol on completed paired dev worlds, without touching their holdout.

This process-local wrapper uses exactly the reference executor's game, prompt,
context and per-episode limits. It never modifies the reference plan or records.
See docs/sol-paired-quest-extension.md.
"""
from __future__ import annotations
import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT))
from scripts import paired_codex_calibration as engine

PARENT_BASE=Path.home()/'.local/share/adndbench/paired-codex-calibrations'
BASE=Path.home()/'.local/share/adndbench/sol-quest-extensions'
SOURCE_MODELS=('gpt-6-luna','gpt-6.2-astra')
SOL='gpt-6.2-sol'
_original_fingerprint=engine.fingerprint


def fingerprint(adapter_name):
    if adapter_name!='quest_trial':raise ValueError('unsupported reference adapter')
    h=hashlib.sha256();h.update(_original_fingerprint(adapter_name).encode()+b'\0')
    path=Path(__file__).resolve();h.update(path.name.encode()+b'\0'+path.read_bytes()+b'\0')
    return h.hexdigest()


def read_reference(name):
    """Read and verify completed reference dev episodes; never return holdout seeds."""
    old=(engine.BASE,engine.MODELS,engine.fingerprint)
    try:
        engine.BASE=PARENT_BASE;engine.MODELS=SOURCE_MODELS;engine.fingerprint=_original_fingerprint
        _,plan,state=engine.load(name)
        if (plan.get('adapter')!='quest_trial' or plan.get('axis')!='quests' or plan.get('level')!='hard'
                or plan.get('models')!=list(SOURCE_MODELS) or plan.get('reasoning_effort')!='low'):
            raise ValueError('reference is not paired hard quest with equal low effort')
        records=[]
        for world,seed,model in engine.specs(plan,'dev'):
            rec=state['episodes'].get(engine.key_for('dev',world,model))
            if not rec or rec.get('status')!='completed':raise ValueError('all reference dev episodes must be complete')
            game,history=engine.reconstruct(plan,seed,rec)
            result=game.result()
            public={k:result[k] for k in ('terminal_reason','turns','invalid_actions','completed_tasks') if k in result}
            records.append({'world':world,'model':model,'result':public,
                            'journal_sha256':engine.digest({'turns':rec['turns'],'result':rec['result']})})
        # Build the snapshot from explicit fields, discarding holdout completely.
        keys=('version','adapter','axis','level','models','reasoning_effort','cli_version','context_turns',
              'max_actions_per_game','max_calls_per_split','max_input_tokens_per_split',
              'call_timeout','max_wall_seconds_per_run','source_sha256','system_prompt')
        spec={k:copy.deepcopy(plan[k]) for k in keys}
        dev_seeds=list(plan['seeds']['dev'])
        return spec,dev_seeds,records,engine.digest({'spec':spec,'dev_seeds':dev_seeds,'records':records})
    finally:
        engine.BASE,engine.MODELS,engine.fingerprint=old


def status(name):
    _,plan,state=engine.load(name)
    rows=[]
    for world,seed,model in engine.specs(plan,'dev'):
        rec=state['episodes'].get(engine.key_for('dev',world,model),{'status':'pending','turns':[]})
        game,_=engine.reconstruct(plan,seed,rec)
        result=game.result() if rec['status']=='completed' else {}
        rows.append({'world':world,'reference':[x for x in plan['reference_dev']['records'] if x['world']==world],
                     'sol':{'status':rec['status'],
                            'result':{k:result[k] for k in ('terminal_reason','turns','invalid_actions','completed_tasks') if k in result}
                                      if rec['status']=='completed' else None}})
    receipts=state['receipts']['dev']
    print(json.dumps({'source':plan['reference_dev']['source_name'], 'axis':plan['axis'], 'level':plan['level'],
          'model':SOL,'effort':engine.EFFORT,'context_turns':plan['context_turns'],'worlds':rows,
          'calls':len(receipts),'reported_input_tokens':sum(x.get('usage',{}).get('input_tokens',0) for x in receipts),
          'unknown_usage_calls':sum('usage' not in x for x in receipts),
          'note':'Dev only, same public game/protocol/seed as verified reference. '
                 'Codex tool use audited, filesystem not fully isolated. Incomplete is not a loss.'},ensure_ascii=False,indent=2))


def configure():
    # All modifications are process-local and cannot alter the reference runner.
    engine.BASE=BASE;engine.MODELS=(SOL,);engine.fingerprint=fingerprint;engine.status=status


def init(name,source):
    spec,dev_seeds,records,origin_sha=read_reference(source)
    plan={**spec,'seeds':{'dev':dev_seeds,'holdout':[]},'models':[SOL],
          'source_sha256':fingerprint(spec['adapter']),
          'reference_dev':{'source_name':source,'reference_dev_sha256':origin_sha,
                           'reference_source_sha256':spec['source_sha256'],'records':records}}
    # Refuse any accidental discrepancy in settings before writing.
    for seed in dev_seeds:engine.create_game(plan,seed).observe()
    configure();d=engine.path_for(name);d.mkdir(parents=True,mode=0o700,exist_ok=True)
    if d.stat().st_mode&0o077 or any(d.iterdir()):raise ValueError('requires new owner-only directory')
    engine.write(d/'plan.json',plan)
    engine.write(d/'state.json',{'sealed':False,'plan_sha256':engine.digest(plan),
                                 'episodes':{},'receipts':{'dev':[],'holdout':[]}})
    print(f'Created private Sol extension for {len(dev_seeds)} verified dev world(s); no holdout copied; no model calls.')


def main():
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='command',required=True)
    a=sub.add_parser('init');a.add_argument('name');a.add_argument('--source',default='radical-quest')
    for command in ('run','status'):
        a=sub.add_parser(command);a.add_argument('name')
    args=ap.parse_args()
    if args.command=='init':init(args.name,args.source)
    else:
        configure()
        if args.command=='run':engine.run(args.name,'dev')
        else:status(args.name)

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,TypeError):
        print('Sol extension stopped; inspect private state. No automatic retry.',file=sys.stderr);sys.exit(1)
