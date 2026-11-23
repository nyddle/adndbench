#!/usr/bin/env python3
"""Add Sol to verified completed dev worlds of the base grouped memory pilot.

Process-local wrapper; source plan and all holdout records remain unchanged.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT))
from scripts import sol_paired_quest_extension as bridge

engine=bridge.engine
BASE=Path.home()/'.local/share/adndbench/sol-memory-extensions'
PARENT_BASE=Path.home()/'.local/share/adndbench/paired-codex-calibrations'
SOL=bridge.SOL
SOURCE_MODELS=bridge.SOURCE_MODELS
_original_fingerprint=bridge._original_fingerprint


def fingerprint(adapter_name):
    if adapter_name!='hard_memory_navigation':raise ValueError('unsupported reference adapter')
    h=hashlib.sha256();h.update(_original_fingerprint(adapter_name).encode()+b'\0')
    for path in (ROOT/'scripts/sol_paired_quest_extension.py',Path(__file__).resolve()):
        h.update(path.name.encode()+b'\0'+path.read_bytes()+b'\0')
    return h.hexdigest()


def read_reference(name):
    """Verify both completed dev episodes before returning only their dev data."""
    old=(engine.BASE,engine.MODELS,engine.fingerprint)
    try:
        engine.BASE=PARENT_BASE;engine.MODELS=SOURCE_MODELS;engine.fingerprint=_original_fingerprint
        _,plan,state=engine.load(name)
        if (plan.get('adapter')!='hard_memory_navigation' or plan.get('axis')!='memory-compact'
                or plan.get('level')!='base' or plan.get('models')!=list(SOURCE_MODELS)
                or plan.get('reasoning_effort')!='low'):
            raise ValueError('reference is not the base paired compact-memory protocol')
        records=[]
        for world,seed,model in engine.specs(plan,'dev'):
            rec=state['episodes'].get(engine.key_for('dev',world,model))
            if not rec or rec.get('status')!='completed':raise ValueError('all reference dev episodes must be complete')
            game,_=engine.reconstruct(plan,seed,rec)
            result=game.result()
            if result.get('config',{}).get('exchanges')!=12:
                raise ValueError('reference is not the 12-exchange base condition')
            public={k:result[k] for k in ('terminal_reason','turns','invalid_actions','completed') if k in result}
            records.append({'world':world,'model':model,'result':public,
                            'journal_sha256':engine.digest({'turns':rec['turns'],'result':rec['result']})})
        keys=('version','adapter','axis','level','models','reasoning_effort','cli_version','context_turns',
              'max_actions_per_game','max_calls_per_split','max_input_tokens_per_split',
              'call_timeout','max_wall_seconds_per_run','source_sha256','system_prompt')
        spec={k:copy.deepcopy(plan[k]) for k in keys}
        dev_seeds=list(plan['seeds']['dev'])
        return spec,dev_seeds,records,engine.digest({'spec':spec,'dev_seeds':dev_seeds,'records':records})
    finally:
        engine.BASE,engine.MODELS,engine.fingerprint=old


def configure_bridge():
    # This modifies only modules within this CLI process, not the reference files.
    bridge.BASE=BASE;bridge.fingerprint=fingerprint;bridge.read_reference=read_reference


def main():
    configure_bridge()
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='command',required=True)
    a=sub.add_parser('init');a.add_argument('name');a.add_argument('--source',default='radical-memory-base')
    for command in ('run','status'):
        a=sub.add_parser(command);a.add_argument('name')
    args=ap.parse_args()
    if args.command=='init':bridge.init(args.name,args.source)
    else:
        bridge.configure()
        if args.command=='run':engine.run(args.name,'dev')
        else:bridge.status(args.name)

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,TypeError):
        print('Sol memory extension stopped; inspect private state. No automatic retry.',file=sys.stderr);sys.exit(1)
