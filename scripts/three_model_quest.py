#!/usr/bin/env python3
"""Three-model replay-verified quest trials on shared private worlds."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts import paired_codex_calibration as engine

MODELS = ('gpt-6-luna', 'gpt-6.2-sol', 'gpt-6.2-astra')
BASE = Path.home() / '.local/share/adndbench/three-model-quests'
_base_fingerprint = engine.fingerprint

def fingerprint(name):
    if name != 'quest_trial':
        raise ValueError('quest adapter required')
    h = hashlib.sha256()
    h.update(_base_fingerprint(name).encode('ascii'))
    h.update(Path(__file__).read_bytes())
    return h.hexdigest()

def status(name):
    _, p, st = engine.load(name)
    groups = []
    for split in ('dev', 'holdout'):
        models = {}
        worlds = []
        for model in MODELS:
            results, states = [], Counter()
            for world, seed, current in engine.specs(p, split):
                if current != model: continue
                rec = st['episodes'].get(engine.key_for(split, world, model), {'status':'pending','turns':[]})
                game, _ = engine.reconstruct(p, seed, rec)
                states[rec['status']] += 1
                if rec['status'] == 'completed': results.append(game.result())
            models[model] = {'planned':len(p['seeds'][split]), 'statuses':dict(states),
                'terminal_games':len(results), 'wins':sum(x['terminal_reason']=='completed' for x in results),
                'outcomes':dict(Counter(x['terminal_reason'] for x in results))}
        for world, seed, current in engine.specs(p, split):
            if current != MODELS[0]: continue
            values = {}
            for model in MODELS:
                rec = st['episodes'].get(engine.key_for(split, world, model), {'status':'pending','turns':[]})
                game, _ = engine.reconstruct(p, seed, rec)
                result = game.result() if rec['status']=='completed' else None
                values[model] = {'status':rec['status'], 'result':result}
            worlds.append({'world':world,'models':values})
        receipts = st['receipts'][split]
        groups.append({'split':split,'models':models,'worlds':worlds,'calls':len(receipts),
          'reported_input_tokens':sum(r.get('usage',{}).get('input_tokens',0) for r in receipts),
          'unknown_usage_calls':sum('usage' not in r for r in receipts)})
    print(json.dumps({'protocol':'quest-trial-0.1.0','level':p['level'], 'models':MODELS,
       'effort':engine.EFFORT, 'sealed':st['sealed'], 'groups':groups,
       'note':'Exploratory Codex; incomplete and technical outcomes are not losses. Tools audited; filesystem not fully isolated.'},ensure_ascii=False,indent=2))

def configure():
    engine.BASE = BASE
    engine.MODELS = MODELS
    engine.fingerprint = fingerprint
    engine.status = status

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    sub=ap.add_subparsers(dest='command',required=True)
    a=sub.add_parser('init'); a.add_argument('name'); a.add_argument('--level',choices=('medium','hard','extreme'),default='extreme')
    a.add_argument('--dev-worlds',type=int,default=2);a.add_argument('--holdout-worlds',type=int,default=3)
    a.add_argument('--max-calls',type=int,default=240);a.add_argument('--max-input-tokens',type=int,default=12000000)
    for cmd in ('run','status','seal'):
        a=sub.add_parser(cmd);a.add_argument('name')
        if cmd=='run':a.add_argument('--split',choices=('dev','holdout'),required=True)
    args=ap.parse_args();configure()
    if args.command=='init':engine.init(args.name,'quest_trial','quests',args.level,args.dev_worlds,args.holdout_worlds,35,args.max_calls,args.max_input_tokens,35)
    elif args.command=='status':status(args.name)
    elif args.command=='seal':engine.seal(args.name)
    else:engine.run(args.name,args.split)

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,TypeError):
        print('Calibration stopped; inspect private state. No automatic retry.',file=sys.stderr);sys.exit(1)
