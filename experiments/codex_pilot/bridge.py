"""Interactive bridge for an individual model player. Private state stays server-side."""
import json
import os
import pickle
import sys
from pathlib import Path

sys.path.insert(0, '/workspace')
from benchmark.engine import Game

mode, run_id, value = sys.argv[1:]
if not run_id.isalnum():
    raise ValueError('bad run id')
path = Path('/tmp/adnd-pilot-' + run_id + '.pickle')
trace = Path('/tmp/adnd-pilot-' + run_id + '.jsonl')
if mode == 'start':
    if path.exists():
        raise RuntimeError('run already started')
    game = Game(int(value), max_turns=120)
    obs = game.observe()
    trace.write_text(json.dumps({'observation': obs}, ensure_ascii=False) + '\n')
elif mode == 'step':
    with path.open('rb') as f:
        game = pickle.load(f)
    action = json.loads(value)
    obs = game.step(action)
    with trace.open('a', encoding='utf8') as f:
        f.write(json.dumps({'action': action, 'observation': obs}, ensure_ascii=False) + '\n')
else:
    raise ValueError('bad mode')
with path.open('wb') as f:
    pickle.dump(game, f)
os.chmod(path, 0o600)
print(json.dumps(obs, ensure_ascii=False))
