#!/usr/bin/env python3
"""Continue ready balanced-memory holdout episodes, never retrying failures.

Uses the independent runner's checkpoint and failure handling with the original
balanced-memory plan, fingerprint, prompt, models, state and cumulative budget.
The supplemental audit records the runner change without changing the plan.
"""
from pathlib import Path
import hashlib
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts import three_model_balanced_memory as balanced
from scripts import independent_gradient_calibration as independent

def run(name):
    balanced.configure_existing(name)
    engine=balanced.engine
    d,plan,state=engine.load(name)
    if not state['sealed']:
        raise ValueError('holdout must be sealed')
    if not any(r.get('status')=='technical_error' for r in state['episodes'].values()):
        raise ValueError('no technical failure to work around')
    if any(r.get('status')=='inflight' for r in state['episodes'].values()):
        raise ValueError('uncertain inflight attempt; inspect, do not retry')
    audit=d/'holdout-continuation-audit.json'
    code_files=[Path(__file__).resolve(),Path(independent.__file__).resolve()]
    code_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in code_files}
    data={'version':'balanced-holdout-continuation-0.1.0',
          'plan_sha256':engine.digest(plan),'independent_runner_sha256':code_hashes,
          'policy':'Continue only ready episodes. Retain technical_error and never retry. Cumulative calls and tokens remain bounded by original plan.',
          'previous_calls':len(state['receipts']['holdout'])}
    if audit.exists():
        raise ValueError('continuation already recorded; inspect before any further run')
    engine.write(audit,data)
    independent.gradient.status=balanced.status
    independent.run(name,'holdout')

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('usage: continue_balanced_holdout.py PLAN')
    try:run(sys.argv[1])
    except (OSError,ValueError,KeyError,TypeError):
        print('Continuation stopped; inspect private state. No automatic retry.',file=sys.stderr);sys.exit(1)
