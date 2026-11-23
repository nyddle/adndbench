"""Reproducible development audit; never use these public seeds for evaluation."""
import json
from collections import Counter
from benchmark.short_memory import LEVELS,LENGTHS,create_game,source_fingerprint


def main():
    n=1000;groups={level:Counter() for level in LEVELS};pairs=Counter()
    for i in range(n):
        answers={}
        for level in LEVELS:
            g=create_game('memory-compact',f'short-audit-{i}',level);o=g.observe()
            holdings={x['person']:x['item'] for x in o['assignments']};initial=dict(holdings)
            events=[]
            while not g.done:
                o=g.observe()
                for e in o.get('events',[]):
                    a,b=e['people'];events.append((a,b));holdings[a],holdings[b]=holdings[b],holdings[a]
                if 'query' in o:
                    item=o['query']['item'];answer=next(k for k,v in holdings.items() if v==item);answers[level]=answer
                    choices=o['query']['candidates'];initial_owner=next(k for k,v in initial.items() if v==item)
                    popularity=Counter(p for pair in events for p in pair)
                    most_active=min(choices,key=lambda p:(-popularity[p],p))
                    x=groups[level];x['first_candidate']+=int(answer==choices[0]);x['initial_owner']+=int(answer==initial_owner)
                    x['last_pair_contains_owner']+=int(answer in events[-1]);x['penultimate_pair_contains_owner']+=int(answer in events[-2])
                    x['most_active_person']+=int(answer==most_active)
                    g.step({'type':'deliver','person':answer})
                else:g.step({'type':'move','direction':'forward'})
            groups[level]['tracker_correct']+=int(g.terminal_reason=='completed' and g.turn==4)
        pairs['same_4_6']+=int(answers['s4']==answers['s6'])
        pairs['same_6_8']+=int(answers['s6']==answers['s8'])
    out={'version':'short-memory-0.1.0','fingerprint':source_fingerprint(),
         'seed_set':'public-short-audit-0..999','worlds':n,
         'groups':{k:dict(v) for k,v in groups.items()},'paired_prefixes':dict(pairs),
         'note':'Development construction audit, no LLM. Each conditional filter and these heuristics change distributions; not a general shortcut proof.'}
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
