#!/usr/bin/env python3
"""Bounded paired Codex calibration; development and holdout are disjoint.

All `init`, `status`, and `seal` operations are offline. `run` contacts Codex.
For details and limitations see docs/paired-codex-calibration.md.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from benchmark.vector_harness import canonical_action

VERSION = 'paired-codex-calibration-0.1.0'
BASE = Path.home() / '.local/share/adndbench/paired-codex-calibrations'
CLI = os.environ.get('ADNDBENCH_CODEX_CLI') or shutil.which('codex') or '/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex'
MODELS = ('gpt-6-luna', 'gpt-6.2-astra')
EFFORT = 'low'
TIMEOUT = 90
MAX_WALL = 3600


def encode(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def digest(obj): return hashlib.sha256(encode(obj)).hexdigest()


def path_for(name):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', name): raise ValueError('invalid plan name')
    return BASE / name


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.write-')
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf8') as f:
            json.dump(data, f, ensure_ascii=False, sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def cli_version():
    return subprocess.run([CLI, '--version'], check=True, capture_output=True, text=True, timeout=10).stdout.strip()


def fingerprint(adapter_name):
    if adapter_name not in ('hard_memory_navigation', 'quest_trial'):
        raise ValueError('unsupported adapter')
    h = hashlib.sha256()
    folder = ROOT / 'benchmark'
    paths = [(name, folder / name) for name in ('__init__.py', 'vector_harness.py', 'fixed_probes.py', adapter_name + '.py')]
    paths.append(('paired_codex_calibration.py', Path(__file__).resolve()))
    for name, p in paths:
        h.update(name.encode() + b'\0' + p.read_bytes() + b'\0')
    return h.hexdigest()


def adapter(name):
    if name not in ('hard_memory_navigation', 'quest_trial'):
        raise ValueError('unsupported adapter')
    return importlib.import_module('benchmark.' + name)


def create_game(p, seed):
    mod = adapter(p['adapter'])
    if p['adapter'] == 'quest_trial':
        return mod.QuestTrial(seed, p['level'])
    if p['axis'] == 'memory-compact':
        return mod.create_compact_memory_game(seed, p['level'])
    return mod.create_game(p['axis'], seed, p['level'])


def rule(p):
    mod = adapter(p['adapter'])
    if p['adapter'] == 'quest_trial': return mod.SYSTEM_PROMPT
    if p['axis'] == 'memory-compact': return mod.COMPACT_MEMORY_PROMPT
    return mod.SYSTEM_PROMPTS[p['axis']]


def actions(p, observation):
    if p['adapter'] == 'quest_trial':
        return [{'type':'perform','target':x['id']} for x in observation['tasks']]
    return adapter(p['adapter']).allowed_actions('memory' if p['axis'] == 'memory-compact' else p['axis'], observation)


def init(name, adapter_name, axis, level, dev_worlds, holdout_worlds, max_actions, max_calls, max_input_tokens, context_turns):
    if adapter_name not in ('hard_memory_navigation', 'quest_trial'): raise ValueError('unsupported adapter')
    if (adapter_name == 'quest_trial' and axis != 'quests') or (adapter_name == 'hard_memory_navigation' and axis not in ('memory','memory-compact','navigation')):
        raise ValueError('invalid axis')
    valid_levels = ('medium','hard','extreme') if axis == 'quests' else ('base','hard','extreme')
    if level not in valid_levels: raise ValueError('invalid level')
    if not (1 <= dev_worlds <= 10 and 1 <= holdout_worlds <= 10 and 1 <= max_actions <= 120 and
            1 <= max_calls <= 1000 and 1 <= max_input_tokens <= 20000000 and 1 <= context_turns <= 120):
        raise ValueError('invalid bounds')
    if axis in ('memory', 'memory-compact'):
        required = ({'base':4, 'hard':8, 'extreme':14} if axis == 'memory-compact' else {'base':14, 'hard':38, 'extreme':74})[level]
        if max_actions < required or context_turns < min(max_actions, required + 4):
            raise ValueError('memory requires enough actions and retained context for the clue')
    seeds = []
    while len(seeds) < dev_worlds + holdout_worlds:
        value = secrets.token_hex(16)
        if value not in seeds: seeds.append(value)
    p = {'version':VERSION,'adapter':adapter_name,'axis':axis,'level':level,
         'seeds':{'dev':seeds[:dev_worlds], 'holdout':seeds[dev_worlds:]},
         'models':list(MODELS),'reasoning_effort':EFFORT,'cli_version':cli_version(),
         'context_turns':context_turns,'max_actions_per_game':max_actions,
         'max_calls_per_split':max_calls,'max_input_tokens_per_split':max_input_tokens,
         'call_timeout':TIMEOUT,'max_wall_seconds_per_run':MAX_WALL,'source_sha256':fingerprint(adapter_name)}
    p['system_prompt'] = rule(p)
    for seed in seeds: create_game(p, seed).observe()
    d = path_for(name); d.mkdir(parents=True, mode=0o700, exist_ok=True)
    if d.stat().st_mode & 0o077 or any(d.iterdir()): raise ValueError('requires new owner-only directory')
    write(d/'plan.json', p)
    write(d/'state.json', {'sealed':False,'plan_sha256':digest(p),'episodes':{}, 'receipts':{'dev':[],'holdout':[]}})
    print(f'Created private plan for {axis}/{level}: {dev_worlds} dev and {holdout_worlds} holdout worlds; no model calls.')


def load(name):
    d = path_for(name)
    p = json.loads((d/'plan.json').read_text())
    st = json.loads((d/'state.json').read_text())
    if (p.get('version') != VERSION or p.get('models') != list(MODELS) or p.get('reasoning_effort') != EFFORT
        or p.get('source_sha256') != fingerprint(p.get('adapter')) or p.get('cli_version') != cli_version() or p.get('system_prompt') != rule(p)):
        raise ValueError('source, model, prompt or CLI changed')
    if st.get('plan_sha256') != digest(p): raise ValueError('plan changed')
    if st.get('sealed') and st.get('sealed_plan_sha256') != digest(p): raise ValueError('sealed plan changed')
    return d,p,st


def specs(p, split):
    for i, seed in enumerate(p['seeds'][split], 1):
        for model in p['models']:
            yield i, seed, model


def key_for(split, world, model): return f'{split}:{world}:{model}'


def reconstruct(p, seed, record):
    game = create_game(p, seed)
    history=[]
    for t in record.get('turns', []):
        obs=game.observe()
        if getattr(game, 'done', False) or digest(obs) != t['observation_sha256']:
            raise ValueError('replay observation mismatch')
        act=t['action']
        if act != canonical_action(act, actions(p,obs)) and act != {'type':'invalid'}:
            raise ValueError('replay noncanonical action')
        history.append({'observation':obs,'action':act})
        game.step(act)
    if record.get('status') == 'completed' and (not getattr(game,'done',False) or record.get('result') != game.result()):
        raise ValueError('terminal replay mismatch')
    return game,history


def prompt(p, history, obs):
    visible = history[-max(0,p['context_turns']-1):] if p['context_turns'] > 1 else []
    public={'rules':p['system_prompt'],'past_turns':visible,'current_observation':obs,
            'possible_action_shapes':actions(p,obs)}
    return ('You are a subject in a turn-based game. Do not use any tools, commands, files, browsers '
            'or external information. Return exactly one JSON action, without Markdown, prose or notes. '
            'Possible actions are syntactic forms and may not be legal now.\n' + encode(public).decode())


def parse_events(text):
    final=[]; usage=None
    for line in text.splitlines():
        try: event=json.loads(line)
        except (ValueError,TypeError): return {'error':'invalid_event_stream'}
        if not isinstance(event,dict): return {'error':'invalid_event_stream'}
        typ=event.get('type','')
        if typ in ('turn.failed','error'): return {'error':'turn_failed'}
        if typ.startswith('item.'):
            item=event.get('item')
            if not isinstance(item,dict): return {'error':'invalid_event_stream'}
            if item.get('type') not in ('agent_message','reasoning'): return {'error':'tool_use_detected'}
            if typ=='item.completed' and item.get('type')=='agent_message' and isinstance(item.get('text'),str): final.append(item['text'])
        if typ=='turn.completed': usage=event.get('usage')
    if not isinstance(usage,dict) or type(usage.get('input_tokens')) is not int or usage['input_tokens'] < 0:
        return {'error':'missing_usage'}
    u={k:usage[k] for k in ('input_tokens','cached_input_tokens','output_tokens') if type(usage.get(k)) is int and usage[k] >= 0}
    if len(final)!=1: return {'error':'unexpected_message_count', 'usage':u}
    def unique(pairs):
        result={}
        for k,v in pairs:
            if k in result: raise ValueError('duplicate key')
            result[k]=v
        return result
    try: action=json.loads(final[0], object_pairs_hook=unique)
    except (ValueError,TypeError,RecursionError): action={'type':'invalid'}
    return {'action':action,'usage':u}


def call(text, model, timeout):
    with tempfile.TemporaryDirectory(prefix='adnd-codex-paired-') as cwd:
        cmd=[CLI,'exec','--ephemeral','--ignore-user-config','--skip-git-repo-check',
             '-s','read-only','-m',model,'-c',f'model_reasoning_effort="{EFFORT}"', '-C',cwd,'--json','-']
        proc=subprocess.Popen(cmd, stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
        try: out,_=proc.communicate(text,timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGKILL);proc.communicate();return {'error':'timeout'}
        except BaseException:
            os.killpg(proc.pid,signal.SIGKILL);proc.communicate();raise
        if proc.returncode: return {'error':'cli_exit'}
        if len(out)>2_000_000: return {'error':'event_stream_too_large'}
        return parse_events(out)


def seal(name):
    d=path_for(name); fd=os.open(d/'.lock',os.O_CREAT|os.O_RDWR,0o600)
    with os.fdopen(fd,'r+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        d,p,st=load(name)
        if st.get('sealed'): raise ValueError('already sealed')
        if any(r.get('status') in ('inflight','technical_error') for r in st['episodes'].values()):
            raise ValueError('unresolved attempt')
        has_pair=any(all(st['episodes'].get(key_for('dev',world,model),{}).get('status') == 'completed'
                         for model in MODELS) for world in range(1,len(p['seeds']['dev'])+1))
        if not has_pair: raise ValueError('complete at least one dev pair before sealing')
        st['sealed'],st['sealed_plan_sha256']=True,digest(p)
        write(d/'state.json',st)
    print('Plan sealed; holdout enabled. No model calls.')


def status(name):
    _,p,st=load(name)
    groups=[]
    for split in ('dev','holdout'):
        model_stats={}
        for model in MODELS:
            episodes=[]
            for world,seed,m in specs(p,split):
                if m != model: continue
                rec=st['episodes'].get(key_for(split,world,model), {'status':'pending','turns':[]})
                game,_=reconstruct(p,seed,rec)
                result=game.result() if rec['status']=='completed' else {}
                episodes.append((rec,result))
            model_stats[model]={'planned':len(episodes), 'statuses':dict(Counter(rec['status'] for rec,_ in episodes)),
                'terminal_reasons':dict(Counter(res.get('terminal_reason') for rec,res in episodes if rec['status']=='completed')),
                'completed_games':sum(rec['status']=='completed' for rec,_ in episodes),
                'successes':sum(res.get('terminal_reason')=='completed' for rec,res in episodes if rec['status']=='completed')}
        pairs=Counter()
        for world,seed,_ in specs(p,split):
            if _ != MODELS[0]: continue
            a=st['episodes'].get(key_for(split,world,MODELS[0]),{})
            b=st['episodes'].get(key_for(split,world,MODELS[1]),{})
            if a.get('status')=='completed' and b.get('status')=='completed':
                ar=a['result'].get('terminal_reason')=='completed';br=b['result'].get('terminal_reason')=='completed'
                pairs[('both' if ar and br else 'luna_only' if ar else 'astra_only' if br else 'neither')]+=1
            else: pairs['incomplete']+=1
        receipts=st['receipts'][split]
        groups.append({'split':split,'models':model_stats,'paired_outcomes':dict(pairs),
                       'calls':len(receipts),'reported_input_tokens':sum(x.get('usage',{}).get('input_tokens',0) for x in receipts),
                       'unknown_usage_calls':sum('usage' not in x for x in receipts)})
    print(json.dumps({'axis':p['axis'],'level':p['level'],'models':list(MODELS), 'effort':EFFORT,
                      'context_turns':p['context_turns'],'sealed':st['sealed'],'groups':groups,
                      'note':'Exploratory Codex, tool use audited but filesystem is not isolated. Missing/limited episodes are not failures. Seeds and logs private.'},ensure_ascii=False,indent=2))


def run(name, split):
    d=path_for(name); fd=os.open(d/'.lock',os.O_CREAT|os.O_RDWR,0o600)
    with os.fdopen(fd,'r+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        d,p,st=load(name)
        if split == 'holdout' and not st['sealed']: raise ValueError('seal before holdout')
        if split == 'dev' and st['sealed']: raise ValueError('development closed after seal')
        if any(r.get('status') in ('inflight','technical_error') for r in st['episodes'].values()):
            raise ValueError('uncertain or failed attempt requires inspection; no automatic retry')
        for world,seed,model in specs(p,split):
            key=key_for(split,world,model)
            if key not in st['episodes']: st['episodes'][key]={'status':'ready','turns':[]}
            reconstruct(p,seed,st['episodes'][key])
        started=time.monotonic()
        stop=False
        while not stop:
            progress=False
            for world,seed,model in specs(p,split):
                rec=st['episodes'][key_for(split,world,model)]
                if rec['status'] != 'ready': continue
                game,history=reconstruct(p,seed,rec)
                if getattr(game,'done',False):
                    rec['status']='completed';rec['result']=game.result();write(d/'state.json',st);continue
                if len(rec['turns']) >= p['max_actions_per_game']:
                    rec['status']='action_limit';write(d/'state.json',st);continue
                receipts=st['receipts'][split]
                if (len(receipts)>=p['max_calls_per_split'] or
                    sum(x.get('usage',{}).get('input_tokens',0) for x in receipts)>=p['max_input_tokens_per_split'] or
                    time.monotonic()-started>=p['max_wall_seconds_per_run']):
                    stop=True;break
                progress=True
                obs=game.observe()
                rec['status']='inflight'
                receipt={'episode':key_for(split,world,model),'number':len(receipts)+1,'status':'inflight'}
                receipts.append(receipt);write(d/'state.json',st)
                remaining=p['max_wall_seconds_per_run']-(time.monotonic()-started)
                answer=call(prompt(p,history,obs),model,min(p['call_timeout'], max(0.1,remaining)))
                if 'error' in answer:
                    rec['status']='technical_error';rec['technical_error']=answer['error'];receipt['status']='technical_error'
                    if 'usage' in answer:receipt['usage']=answer['usage']
                    write(d/'state.json',st);stop=True;break
                action=canonical_action(answer['action'],actions(p,obs))
                game.step(action)
                rec['turns'].append({'observation_sha256':digest(obs),'action':action})
                rec['status']='completed' if getattr(game,'done',False) else 'ready'
                if rec['status']=='completed': rec['result']=game.result()
                receipt.update(status='completed',usage=answer['usage'])
                write(d/'state.json',st)
                print(f'{split} world {world}: {model}, {len(rec["turns"])} actions',flush=True)
            if not progress: break
        write(d/'state.json',st)
    status(name)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('init');a.add_argument('name');a.add_argument('--adapter',choices=('hard_memory_navigation','quest_trial'),required=True)
    a.add_argument('--axis',choices=('memory','memory-compact','navigation','quests'),required=True);a.add_argument('--level',required=True)
    a.add_argument('--dev-worlds',type=int,default=2);a.add_argument('--holdout-worlds',type=int,default=3)
    a.add_argument('--max-actions',type=int,default=100);a.add_argument('--max-calls',type=int,default=120)
    a.add_argument('--max-input-tokens',type=int,default=3000000);a.add_argument('--context-turns',type=int,default=120)
    for c in ('seal','status'):
        a=sub.add_parser(c);a.add_argument('name')
    a=sub.add_parser('run');a.add_argument('name');a.add_argument('--split',choices=('dev','holdout'),required=True)
    a=parser.parse_args()
    if a.cmd=='init': init(a.name,a.adapter,a.axis,a.level,a.dev_worlds,a.holdout_worlds,a.max_actions,a.max_calls,a.max_input_tokens,a.context_turns)
    elif a.cmd=='seal': seal(a.name)
    elif a.cmd=='status': status(a.name)
    else: run(a.name,a.split)

if __name__=='__main__':
    try: main()
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError):
        print('Calibration stopped; inspect private state. No automatic retry.',file=sys.stderr);sys.exit(1)
