import json, statistics, collections, time
from benchmark.runner import BaselineAgent, run_episode

runs=[]
start=time.monotonic()
for seed in range(10000):
    episode=run_episode(seed, BaselineAgent(), max_turns=120, probes=False)
    r=episode['result']
    runs.append({k:r[k] for k in ('seed','turns','terminal_reason','quests_completed','quests_total','moves','invalid_actions','rooms_visited','rooms_total','attacks','damage_taken','potions_used')})

def quantiles(values):
    values=sorted(values)
    return {'min':values[0], 'p10':values[int(.10*(len(values)-1))], 'median':statistics.median(values), 'p90':values[int(.90*(len(values)-1))], 'p95':values[int(.95*(len(values)-1))], 'max':values[-1], 'mean':statistics.mean(values)}
completed=[r for r in runs if r['terminal_reason']=='completed']
noncompleted=[r for r in runs if r['terminal_reason']!='completed']
summary={'seeds':'0..9999 inclusive','n':len(runs),'terminal_reasons':dict(collections.Counter(r['terminal_reason'] for r in runs)), 'quest_counts':dict(collections.Counter(r['quests_completed'] for r in runs)), 'completed_turns':quantiles([r['turns'] for r in completed]),'all_turns':quantiles([r['turns'] for r in runs]),'damage_taken':quantiles([r['damage_taken'] for r in runs]),'invalid_actions_total':sum(r['invalid_actions'] for r in runs),'invalid_action_seeds':sum(r['invalid_actions']>0 for r in runs),'potions_used':dict(collections.Counter(r['potions_used'] for r in runs)),'unfinished_sample':noncompleted[:10], 'seconds':round(time.monotonic()-start,2)}
print(json.dumps(summary,indent=2))
