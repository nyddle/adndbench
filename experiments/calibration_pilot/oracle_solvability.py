"""Privileged-map solvability check, not an agent or LLM benchmark.

Run: PYTHONPATH=. python experiments/calibration_pilot/oracle_solvability.py
"""
from collections import deque
from benchmark.expedition import Game

def fight(g):
 while g.observe()['enemy']:
  o=g.observe(); intent=o['enemy']['intent']; hp=o['enemy']['hp']
  if g.hp<=8 and g.potions and intent['damage']<=2: action={'type':'potion'}
  elif not g.braced and intent['damage']>1 and hp>3: action={'type':'defend'}
  else: action={'type':'attack'}
  g.step(action)
  if g.done: raise RuntimeError('encounter ended game: '+str(g.terminal_reason))

def travel(g,target):
 rooms={r['id']:r for r in g.world['rooms']}
 blocked={rid for rid,e in g.encounters.items() if e['hp']>0 and rid!=target}
 q=deque([(g.position,[])]); seen={g.position}
 while q:
  room,path=q.popleft()
  if room==target: break
  for direction,dest in rooms[room]['exits'].items():
   if dest not in seen and dest not in blocked:
    seen.add(dest); q.append((dest,path+[direction]))
 else: raise RuntimeError('safe path unavailable')
 for direction in path:
  fight(g); g.step({'type':'move','direction':direction})
  if g.done: raise RuntimeError('travel ended game: '+str(g.terminal_reason))
 fight(g)

for seed in (101,102):
 for variant in ('easy','hard','npconly','combatonly'):
  levels={'easy':('easy','easy','easy'),'hard':('hard','hard','hard'),'npconly':('easy','easy','hard'),'combatonly':('easy','hard','easy')}
  q,c,n=levels[variant]
  g=Game(seed,max_turns=600,quest_difficulty=q,combat_difficulty=c,npc_difficulty=n,enemy_count=2 if variant.endswith('only') else None)
  required=[q for q in g.plan['quests'] if q['required']]; objectives=[o for q in required for o in q['objectives']]
  while not g.done:
   done=set(g.quest_state['completed_objectives']); choices=[o for o in objectives if o['id'] not in done and set(o['requires'])<=done]
   if not choices: raise RuntimeError('required graph blocked')
   objective=choices[0]; travel(g,objective['room_id'])
   if objective['id'] in g.quest_state['completed_objectives']: continue
   g.step({'type':objective['event']})
   if g.terminal_reason not in (None,'completed'): raise RuntimeError('failed during action')
  print(seed,variant,g.terminal_reason,g.turn,g.result()['invalid_actions'])
