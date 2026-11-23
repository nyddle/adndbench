"""Bridge for one-action-at-a-time exploratory Codex agent sessions."""
import json
import os
import pickle
import sys
from pathlib import Path
sys.path.insert(0, '/workspace')
from benchmark.expedition import Game
mode, run_id, value = sys.argv[1:]
if not run_id.isalnum():
    raise ValueError('bad run id')
path = Path('/tmp/adnd-cal-' + run_id + '.pickle')
trace = Path('/tmp/adnd-cal-' + run_id + '.jsonl')
if mode == 'start':
    if path.exists():
        raise RuntimeError('run already started')
    level, _, seed_text = value.partition(':')
    axis = {'npconly': ('easy', 'easy', 'hard'), 'combatonly': ('easy', 'hard', 'easy')}
    quest_level, combat_level, npc_level = axis.get(level, (level, level, level))
    game = Game(int(seed_text or '101'), max_turns=600, map_size=6, map_topology='mixed',
                terrain_diversity=2, quest_difficulty=quest_level, combat_difficulty=combat_level,
                npc_difficulty=npc_level, character_class='generalist',
                enemy_count=2 if level in axis else None)
    obs = game.observe()
    trace.write_text(json.dumps({'observation': obs}, ensure_ascii=False) + '\n')
elif mode == 'peek':
    with path.open('rb') as f:
        game = pickle.load(f)
    obs = game.observe()
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
