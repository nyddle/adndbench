import json, collections
from benchmark.runner import BaselineAgent,run_episode
output={}
for limit in (60,80,100,120,140,160,200):
    outcomes=collections.Counter()
    for seed in range(3000):
        r=run_episode(seed,BaselineAgent(),max_turns=limit,probes=False)['result']
        outcomes[r['terminal_reason']]+=1
    output[limit]=dict(outcomes)
print(json.dumps(output,indent=2))
